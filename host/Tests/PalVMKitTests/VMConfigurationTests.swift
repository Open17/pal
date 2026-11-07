import Foundation
import Testing
@testable import PalVMKit

@Suite struct VMConfigurationTests {
    let json = """
        {
          "version": 1,
          "cpuCount": 4,
          "memorySizeMiB": 8192,
          "diskImage": "disk.img",
          "seedImage": "seed.iso",
          "efiVariableStore": "efi-vars.fd",
          "machineIdentifier": "machine-id",
          "macAddress": "02:0a:3b:4c:5d:6e",
          "consoleLog": "console.log"
        }
        """

    @Test func decodesImageBuilderOutput() throws {
        let configuration = try JSONDecoder().decode(VMConfiguration.self, from: Data(json.utf8))
        #expect(configuration == VMConfiguration(macAddress: "02:0a:3b:4c:5d:6e"))
    }

    @Test func resolvesRelativeAndAbsolutePaths() {
        let configuration = VMConfiguration(macAddress: "02:00:00:00:00:01")
        let directory = URL(fileURLWithPath: "/vm")
        #expect(configuration.resolve("disk.img", in: directory).path == "/vm/disk.img")
        #expect(configuration.resolve("/elsewhere/disk.img", in: directory).path == "/elsewhere/disk.img")
    }

    @Test func rejectsUnknownVersions() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try json.replacingOccurrences(of: "\"version\": 1", with: "\"version\": 9")
            .write(to: url, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(throws: PalHostError.unsupportedConfiguration(version: 9)) {
            try VMConfiguration.load(from: url)
        }
    }

    @Test func missingFileExplainsHowToBuild() {
        let error = #expect(throws: PalHostError.self) {
            try VMConfiguration.load(from: URL(fileURLWithPath: "/nonexistent/config.json"))
        }
        #expect(error?.description.contains("build-image.sh") == true)
    }
}
