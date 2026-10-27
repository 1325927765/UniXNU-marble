// SPDX-License-Identifier: BSD-2-Clause-Patent
// QEMU-only preparation of actual owned RAM buffers for the exact phone reader.
// No fixture code is included in the phone firmware volume.
#include <Uefi.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DevicePathLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>

typedef struct {
  UINT8 Magic[16]; UINT64 Address; UINT64 Size; UINT32 Crc; UINT32 Version;
  UINT64 Frequency; UINT64 BootCpu; UINT64 Reserved;
} PAYLOAD;

STATIC EFI_STATUS StartFile (EFI_HANDLE Parent, EFI_HANDLE Volume, CHAR16 *Name)
{
  EFI_HANDLE Image = NULL;
  EFI_DEVICE_PATH_PROTOCOL *Path = FileDevicePath (Volume, Name);
  EFI_STATUS Status;
  if (Path == NULL) { return EFI_OUT_OF_RESOURCES; }
  Status = gBS->LoadImage (FALSE, Parent, Path, NULL, 0, &Image);
  FreePool (Path);
  if (!EFI_ERROR (Status)) { Status = gBS->StartImage (Image, NULL, NULL); }
  return Status;
}

EFI_STATUS EFIAPI FixtureEntry (EFI_HANDLE Image, EFI_SYSTEM_TABLE *Table)
{
  EFI_LOADED_IMAGE_PROTOCOL *Loaded;
  EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *Fs;
  EFI_FILE_PROTOCOL *Root, *File;
  EFI_STATUS Status;
  EFI_PHYSICAL_ADDRESS Fd = 0xA7100000, Fat = 0xA8000000;
  UINTN Size = 64 * 1024 * 1024;
  PAYLOAD Descriptor = {{0},0xA8000000,64*1024*1024,0,1,0,0,0};
  Status = gBS->HandleProtocol (Image, &gEfiLoadedImageProtocolGuid, (VOID **)&Loaded);
  if (EFI_ERROR (Status)) { return Status; }
  Status = gBS->HandleProtocol (Loaded->DeviceHandle, &gEfiSimpleFileSystemProtocolGuid, (VOID **)&Fs);
  if (EFI_ERROR (Status)) { return Status; }
  Status = Fs->OpenVolume (Fs, &Root);
  if (EFI_ERROR (Status)) { return Status; }
  Status = gBS->AllocatePages (AllocateAddress, EfiLoaderData, EFI_SIZE_TO_PAGES (0x300000), &Fd);
  if (EFI_ERROR (Status)) { return Status; }
  Status = gBS->AllocatePages (AllocateAddress, EfiLoaderData, EFI_SIZE_TO_PAGES (Size), &Fat);
  if (EFI_ERROR (Status)) { return Status; }
  ZeroMem ((VOID *)(UINTN)Fd, 0x300000);
  Status = Root->Open (Root, &File, L"\\payload-fat.img", EFI_FILE_MODE_READ, 0);
  if (EFI_ERROR (Status)) { return Status; }
  Status = File->Read (File, &Size, (VOID *)(UINTN)Fat);
  File->Close (File);
  if (EFI_ERROR (Status) || Size != Descriptor.Size) { return EFI_BAD_BUFFER_SIZE; }
  CopyMem (Descriptor.Magic, "MARBLEXNUPAYLD1", 16);
  __asm__ volatile ("mrs %0, cntfrq_el0" : "=r" (Descriptor.Frequency));
  __asm__ volatile ("mrs %0, mpidr_el1" : "=r" (Descriptor.BootCpu));
  Descriptor.BootCpu &= 0xFF00FFFFFFULL;
  Status = gBS->CalculateCrc32 ((VOID *)(UINTN)Fat, Size, &Descriptor.Crc);
  if (EFI_ERROR (Status)) { return Status; }
  if (!EFI_ERROR (Root->Open (Root, &File, L"\\bad-crc.flag", EFI_FILE_MODE_READ, 0))) {
    Descriptor.Crc ^= 1; File->Close (File);
  }
  if (!EFI_ERROR (Root->Open (Root, &File, L"\\bad-address.flag", EFI_FILE_MODE_READ, 0))) {
    Descriptor.Address = 0xB8000000; File->Close (File);
  }
  Root->Close (Root);
  CopyMem ((VOID *)(UINTN)(Fd + 4096), &Descriptor, sizeof (Descriptor));
  Status = StartFile (Image, Loaded->DeviceHandle, L"\\DarwinBoot.efi");
  if (EFI_ERROR (Status)) { return Status; }
  Print (L"QEMU-PAYLOAD-FIXTURE: owned buffers ready\n");
  Status = StartFile (Image, Loaded->DeviceHandle, L"\\MarblePayloadBoot.efi");
  Print (L"QEMU-PAYLOAD-FIXTURE: reader returned %r\n", Status);
  return Status;
}
