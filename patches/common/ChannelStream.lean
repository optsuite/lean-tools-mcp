/-
Copyright (c) 2024 Lean FRO. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.

Authors: lean-tools-mcp
-/

module

prelude
public import Std.Sync.Channel
public import Lean.Data.Lsp.Communication

/-! Channel ↔ FS.Stream adapters for in-process FileWorker communication.

These adapters allow a FileWorker running as a Task (rather than a separate process)
to communicate through `Std.Channel` while the existing `mainLoop` code continues
to read/write via `FS.Stream`.

## Input adapter (`channelInputStream`)
Wraps a `Std.Channel String` as an `FS.Stream`. The channel carries complete
serialized LSP messages in wire format (`Content-Length: N\r\n\r\n{json}`).
The stream adapter maintains an internal byte buffer and serves `getLine`/`read`
from it, blocking on `Channel.recv` when the buffer is exhausted.

## Output adapter (`channelOutputStream`)
An `FS.Stream` that accumulates `putStr` calls into a buffer and sends the
accumulated string through a `Std.Channel String` on `flush`. Since
`writeSerializedLspMessage` calls `putStr` once with the full wire-format
message and then `flush`, each flush corresponds to one complete LSP message.
-/

public section

namespace Lean.Server

open IO

/-- Create an `FS.Stream` that reads from a `Std.Channel String`.

The channel should carry complete LSP wire-format messages
(`Content-Length: N\r\n\r\n{json}`). The stream provides `getLine` and `read`
that consume from an internal buffer, blocking on the channel when more data
is needed. -/
def channelInputStream (ch : Std.Channel String) : IO FS.Stream := do
  let bufRef ← IO.mkRef ByteArray.empty
  let posRef ← IO.mkRef (0 : Nat)
  return {
    flush := pure ()

    read := fun n => do
      let mut buf ← bufRef.get
      let mut pos ← posRef.get
      -- Refill buffer from channel if needed
      while pos + n.toNat > buf.size do
        let msg ← ch.sync.recv
        if msg.isEmpty then
          throw (IO.userError "channelInputStream: EOF")
        let newBytes := msg.toUTF8
        if pos > 0 then
          -- Compact: discard consumed prefix
          buf := buf.extract pos buf.size |>.append newBytes
          pos := 0
        else
          buf := buf.append newBytes
      let result := buf.extract pos (pos + n.toNat)
      posRef.set (pos + n.toNat)
      bufRef.set buf
      return result

    write := fun _ => throw (IO.userError "channelInputStream: write not supported")

    getLine := do
      let mut buf ← bufRef.get
      let mut pos ← posRef.get
      -- Search for newline, refilling from channel as needed
      let mut found := false
      let mut nlPos := pos
      while !found do
        -- Scan for '\n' in buffer[pos..]
        nlPos := pos
        while nlPos < buf.size do
          if buf.get! nlPos == '\n'.toUInt8 then
            found := true
            break
          nlPos := nlPos + 1
        if !found then
          let msg ← ch.sync.recv
          if msg.isEmpty then
            throw (IO.userError "channelInputStream: EOF")
          let newBytes := msg.toUTF8
          if pos > 0 then
            buf := buf.extract pos buf.size |>.append newBytes
            pos := 0
            nlPos := 0
          else
            buf := buf.append newBytes
      -- nlPos points to '\n', include it in the result
      let lineBytes := buf.extract pos (nlPos + 1)
      posRef.set (nlPos + 1)
      bufRef.set buf
      match String.fromUTF8? lineBytes with
      | some s => return s
      | none => throw (IO.userError "channelInputStream: invalid UTF-8 in getLine")

    putStr := fun _ => throw (IO.userError "channelInputStream: putStr not supported")

    isTty := pure false
  }

/-- Create an `FS.Stream` that writes to a `Std.Channel String`.

`putStr` accumulates into an internal buffer. `flush` sends the accumulated
content as a single string through the channel and clears the buffer.
This matches the behavior of `writeSerializedLspMessage`, which calls
`putStr` once with `Content-Length` header + JSON body, then `flush`. -/
def channelOutputStream (ch : Std.Channel String) : IO FS.Stream := do
  let bufRef ← IO.mkRef ""
  return {
    flush := do
      let buf ← bufRef.get
      if !buf.isEmpty then
        ch.sync.send buf
        bufRef.set ""

    read := fun _ => throw (IO.userError "channelOutputStream: read not supported")

    write := fun bs => do
      match String.fromUTF8? bs with
      | some s => bufRef.modify (· ++ s)
      | none => throw (IO.userError "channelOutputStream: invalid UTF-8 in write")

    getLine := throw (IO.userError "channelOutputStream: getLine not supported")

    putStr := fun s => bufRef.modify (· ++ s)

    isTty := pure false
  }

/-- Serialize a `JsonRpc.Message` to LSP wire format and send through a channel.

This is the counterpart of `channelInputStream`: the sender serializes messages
into wire format, and the input stream adapter deserializes them. -/
def sendLspMessage (ch : Std.Channel String) (msg : JsonRpc.Message) : IO Unit := do
  let json := (toJson msg).compress
  let wireMsg := s!"Content-Length: {json.utf8ByteSize}\r\n\r\n{json}"
  ch.sync.send wireMsg

end Lean.Server

end -- public section
