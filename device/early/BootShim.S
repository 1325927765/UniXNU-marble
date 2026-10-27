// SPDX-License-Identifier: BSD-2-Clause-Patent
// Derived from the pinned marble BootShim. Only the FD is relocated; the FAT
// stays in the board's reserved Android kernel buffer. An uncompressed raw FV
// record publishes its address. The application checks bounds and CRC before use.
_Head:
  adr x1, _Payload
  b _Start
  .quad FD_BASE
  .quad IMAGE_SIZE
  .quad 0, 0, 0, 0
  .ascii "ARM\x64"
  .long 0
_Start:
  mov x4, x1
  ldr x5, =FD_BASE
  cmp x4, x5
  beq _Publish
  ldr x6, =FD_SIZE
_Copy:
  ldp x2, x3, [x4], #16
  stp x2, x3, [x5], #16
  subs x6, x6, #16
  b.ne _Copy
_Publish:
  adr x4, _Head
  ldr x6, =PAYLOAD_OFFSET
  add x4, x4, x6
  ldr x6, =0xA8000000
  cmp x4, x6
  b.lo _Entry
  ldr x6, =PAYLOAD_SIZE
  adds x7, x4, x6
  b.cs _Entry
  ldr x6, =0xB8000000
  cmp x7, x6
  b.hi _Entry
  ldr x5, =FD_BASE
  ldr x6, =DESCRIPTOR_OFFSET + 16
  // FFS raw section data is only four-byte aligned. Publish the u64 using
  // aligned word stores, including when firmware enters with SCTLR.A set.
  add x5, x5, x6
  str w4, [x5]
  lsr x7, x4, #32
  str w7, [x5, #4]
_Entry:
  ldr x5, =FD_BASE
  br x5
.ltorg
.balign 16
_Payload:
