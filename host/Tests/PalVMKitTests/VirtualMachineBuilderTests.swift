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

        let configuration = VMConfiguration(cpuCount: 2, memorySizeMiB: 1024, macAddress: "02:0a:3b:4c:5d:6e")
        // Validation needs the virtualization entitlement, which test runners lack.
        let vm = try VirtualMachineBuilder(configuration: configuration, directory: directory)
            .build(validate: false)
        #expect(vm.cpuCount == 2)
        #expect(vm.memorySize == 1024 << 20)
        #expect(vm.storageDevices.count == 1)  // no seed image present
        #expect(vm.networkDevices.first?.macAddress.string == "02:0a:3b:4c:5d:6e")
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
        let configuration = VMConfiguration(macAddress: "02:0a:3b:4c:5d:6e")
        #expect(throws: PalHostError.missingDisk(directory.appendingPathComponent("disk.img").path)) {
            try VirtualMachineBuilder(configuration: configuration, directory: directory)
                .build(validate: false)
        }
    }

    @Test func invalidMACIsReported() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        FileManager.default.createFile(atPath: directory.appendingPathComponent("disk.img").path, contents: Data(count: 4096))
        let configuration = VMConfiguration(macAddress: "zz")
        #expect(throws: PalHostError.invalidMACAddress("zz")) {
            try VirtualMachineBuilder(configuration: configuration, directory: directory)
                .build(validate: false)
        }
    }
}
