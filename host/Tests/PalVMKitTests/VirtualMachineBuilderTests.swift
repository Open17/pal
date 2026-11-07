import Foundation
import Testing
@testable import PalVMKit

@Suite struct VirtualMachineBuilderTests {
    func makeDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("pal-vm-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    @Test func buildsAValidConfiguration() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let disk = directory.appendingPathComponent("disk.img")
        FileManager.default.createFile(atPath: disk.path, contents: nil)
        try FileHandle(forWritingTo: disk).truncate(atOffset: 64 << 20)

        let configuration = VMConfiguration(cpuCount: 2, memorySizeMiB: 1024)
        // Validation needs the virtualization entitlement, which test runners lack.
        let vm = try VirtualMachineBuilder(configuration: configuration, directory: directory)
            .build(validate: false)
        #expect(vm.cpuCount == 2)
        #expect(vm.memorySize == 1024 << 20)
        #expect(vm.storageDevices.count == 1)  // no seed image present
        #expect(vm.networkDevices.isEmpty)  // the guest has no way onto any network
        #expect(vm.socketDevices.count == 1)
        #expect(vm.directorySharingDevices.isEmpty)
        #expect(vm.graphicsDevices.isEmpty)

        // Firmware store and machine identity are created once and reused.
        let identifier = try Data(contentsOf: directory.appendingPathComponent("machine-id"))
        _ = try VirtualMachineBuilder(configuration: configuration, directory: directory)
            .build(validate: false)
        #expect(try Data(contentsOf: directory.appendingPathComponent("machine-id")) == identifier)
        #expect(FileManager.default.fileExists(atPath: directory.appendingPathComponent("efi-vars.fd").path))
    }

    @Test func missingDiskIsReported() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let configuration = VMConfiguration()
        #expect(throws: PalHostError.missingDisk(directory.appendingPathComponent("disk.img").path)) {
            try VirtualMachineBuilder(configuration: configuration, directory: directory)
                .build(validate: false)
        }
    }
}
