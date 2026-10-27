// SPDX-License-Identifier: BSD-2-Clause-Patent
// Real read-only Block I/O over a FAT payload in the board's reserved kernel
// buffer. No physical disk writes, storage driver emulation or fake completions.
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DevicePathLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PcdLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Library/UniXNULib.h>
#include <Protocol/BlockIo.h>
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>
#include <Protocol/UniXNULoader.h>

typedef struct {
  UINT8 Magic[16];
  UINT64 Address;
  UINT64 Size;
  UINT32 Crc;
  UINT32 Version;
  UINT64 Frequency;
  UINT64 BootCpu;
  UINT64 Reserved;
} PAYLOAD;
STATIC_ASSERT (sizeof (PAYLOAD) == 64, "Payload ABI");
STATIC CONST UINT8 mMagic[16] = "MARBLEXNUPAYLD1";
STATIC PAYLOAD mPayload;
STATIC EFI_BLOCK_IO_MEDIA mMedia;
STATIC EFI_GUID mDarwinBootFile = {0x1b64af87,0x8415,0x4b57,{0x9b,0x16,0x68,0x0d,0x70,0x91,0x3b,0x9f}};
STATIC struct { VENDOR_DEVICE_PATH Vendor; EFI_DEVICE_PATH_PROTOCOL End; } mPath = {
  {{HARDWARE_DEVICE_PATH, HW_VENDOR_DP, {sizeof (VENDOR_DEVICE_PATH),0}},
   {0xe89ac568,0x1d84,0x44c3,{0x8f,0x7b,0xc7,0xda,0x84,0xf6,0xe2,0xe0}}},
  {END_DEVICE_PATH_TYPE, END_ENTIRE_DEVICE_PATH_SUBTYPE, {END_DEVICE_PATH_LENGTH,0}}
};

STATIC EFI_STATUS EFIAPI Reset (EFI_BLOCK_IO_PROTOCOL *This, BOOLEAN Extended) { return EFI_SUCCESS; }
STATIC EFI_STATUS EFIAPI Write (EFI_BLOCK_IO_PROTOCOL *This, UINT32 Id, EFI_LBA Lba, UINTN Size, VOID *Buffer) { return EFI_WRITE_PROTECTED; }
STATIC EFI_STATUS EFIAPI Flush (EFI_BLOCK_IO_PROTOCOL *This) { return EFI_SUCCESS; }
STATIC EFI_STATUS EFIAPI
Read (EFI_BLOCK_IO_PROTOCOL *This, UINT32 Id, EFI_LBA Lba, UINTN Size, VOID *Buffer)
{
  if (Id != mMedia.MediaId) { return EFI_MEDIA_CHANGED; }
  if (Size == 0) { return EFI_SUCCESS; }
  if (Buffer == NULL) { return EFI_INVALID_PARAMETER; }
  if (Size % 512 != 0) { return EFI_BAD_BUFFER_SIZE; }
  if (Lba > mMedia.LastBlock || Size / 512 > mMedia.LastBlock + 1 - Lba) { return EFI_INVALID_PARAMETER; }
  CopyMem (Buffer, (VOID *)(UINTN)(mPayload.Address + Lba * 512), Size);
  return EFI_SUCCESS;
}
STATIC EFI_BLOCK_IO_PROTOCOL mBlock = {EFI_BLOCK_IO_PROTOCOL_REVISION, &mMedia, Reset, Read, Write, Flush};

STATIC EFI_STATUS
LoaderReady (EFI_HANDLE Image)
{
  UNIXNU_LOADER_PROTOCOL *Loader;
  EFI_STATUS Status;
  EFI_LOADED_IMAGE_PROTOCOL *Loaded;
  MEDIA_FW_VOL_FILEPATH_DEVICE_PATH Node;
  EFI_DEVICE_PATH_PROTOCOL *Path;
  EFI_HANDLE Driver = NULL;
  Status = gBS->LocateProtocol (&gUniXNULoaderProtocolGuid, NULL, (VOID **)&Loader);
  if (EFI_ERROR (Status)) {
    Status = gBS->HandleProtocol (Image, &gEfiLoadedImageProtocolGuid, (VOID **)&Loaded);
    if (EFI_ERROR (Status) || DevicePathFromHandle (Loaded->DeviceHandle) == NULL) { return EFI_NOT_FOUND; }
    EfiInitializeFwVolDevicepathNode (&Node, &mDarwinBootFile);
    Path = AppendDevicePathNode (DevicePathFromHandle (Loaded->DeviceHandle), (EFI_DEVICE_PATH_PROTOCOL *)&Node);
    if (Path == NULL) { return EFI_OUT_OF_RESOURCES; }
    Status = gBS->LoadImage (FALSE, Image, Path, NULL, 0, &Driver);
    FreePool (Path);
    if (EFI_ERROR (Status)) { return Status; }
    Status = gBS->StartImage (Driver, NULL, NULL);
    if (EFI_ERROR (Status) && Status != EFI_ALREADY_STARTED) { return Status; }
    Status = gBS->LocateProtocol (&gUniXNULoaderProtocolGuid, NULL, (VOID **)&Loader);
  }
  if (EFI_ERROR (Status)) { return Status; }
  return Loader != NULL && Loader->Revision == UNIXNU_LOADER_REVISION && Loader->Boot != NULL ? EFI_SUCCESS : EFI_UNSUPPORTED;
}

EFI_STATUS EFIAPI
PayloadEntry (EFI_HANDLE Image, EFI_SYSTEM_TABLE *SystemTable)
{
  EFI_STATUS Status;
  UINT8 *Fd = (UINT8 *)(UINTN)FixedPcdGet64 (PcdFdBaseAddress);
  UINTN Length = FixedPcdGet32 (PcdFdSize), Offset, Matches = 0;
  UINT32 Crc;
  UINT64 Frequency, Mpidr, El;
  EFI_HANDLE Handle = NULL;
  EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *FileSystem;
  gBS->SetWatchdogTimer (0, 0, 0, NULL);
  Print (L"MARBLE SOURCE XNU EARLY TEST\n");
  for (Offset = 0; Offset + sizeof (PAYLOAD) <= Length; Offset += 4) {
    if (CompareMem (Fd + Offset, mMagic, sizeof (mMagic)) == 0) {
      CopyMem (&mPayload, Fd + Offset, sizeof (mPayload));
      Matches++;
    }
  }
  if (Matches != 1 || mPayload.Version != 1 || mPayload.Reserved != 0 || mPayload.Address < 0xA8000000ULL ||
      mPayload.Size != 64 * 1024 * 1024 || mPayload.Address > 0xB8000000ULL - mPayload.Size ||
      (mPayload.Address & 4095) != 0) { Status = EFI_COMPROMISED_DATA; goto Fail; }
  __asm__ volatile ("mrs %0, CurrentEL" : "=r" (El));
  __asm__ volatile ("mrs %0, cntfrq_el0" : "=r" (Frequency));
  __asm__ volatile ("mrs %0, mpidr_el1" : "=r" (Mpidr));
  Print (L"EL%lu CPU=0x%lx timer=%lu Hz\n", El >> 2, Mpidr, Frequency);
  if (El != 4 || Frequency != mPayload.Frequency || (Mpidr & 0xFF00FFFFFFULL) != mPayload.BootCpu) {
    Status = EFI_UNSUPPORTED; goto Fail;
  }
  Status = gBS->CalculateCrc32 ((VOID *)(UINTN)mPayload.Address, (UINTN)mPayload.Size, &Crc);
  if (EFI_ERROR (Status) || Crc != mPayload.Crc) { Status = EFI_CRC_ERROR; goto Fail; }
  Status = LoaderReady (Image);
  if (EFI_ERROR (Status)) { goto Fail; }
  ZeroMem (&mMedia, sizeof (mMedia));
  mMedia.MediaId = 1; mMedia.MediaPresent = TRUE; mMedia.ReadOnly = TRUE;
  mMedia.BlockSize = 512; mMedia.IoAlign = 1; mMedia.LastBlock = mPayload.Size / 512 - 1;
  Status = gBS->InstallMultipleProtocolInterfaces (&Handle, &gEfiDevicePathProtocolGuid, &mPath,
                     &gEfiBlockIoProtocolGuid, &mBlock, NULL);
  if (EFI_ERROR (Status)) { goto Fail; }
  Status = gBS->ConnectController (Handle, NULL, NULL, TRUE);
  if (EFI_ERROR (Status)) { goto Fail; }
  Status = gBS->HandleProtocol (Handle, &gEfiSimpleFileSystemProtocolGuid, (VOID **)&FileSystem);
  if (EFI_ERROR (Status)) { goto Fail; }
  Print (L"MARBLE-PAYLOAD: real read-only FAT CRC and filesystem PASS\n");
  return UniXNURun (Image, UniXNUHostFirmware);
Fail:
  Print (L"MARBLE-PAYLOAD: refused %r; boot services retained\n", Status);
  return Status;
}
