import Foundation
import Testing
@testable import PalVMKit

@Suite struct VMConfigurationTests {
    let json = """
        {
          "version": 2,
          "cpuCount": 4,
          "memorySizeMiB": 8192,
          "diskImage": "disk.img",
          "seedImage": "seed.iso",
          "efiVariableStore": "efi-vars.fd",
          "machineIdentifier": "machine-id",
          "consoleLog": "console.log",
          "forwardedPorts": [{"name": "api", "hostPort": 8765, "guestPort": 8765}]
        }
        """

    @Test func decodesImageBuilderOutput() throws {
        let configuration = try JSONDecoder().decode(VMConfiguration.self, from: Data(json.utf8))
        #expect(configuration == VMConfiguration(forwardedPorts: [PortForward(name: "api", hostPort: 8765, guestPort: 8765)]))
    }

    @Test func resolvesRelativeAndAbsolutePaths() {
        let configuration = VMConfiguration()
        let directory = URL(fileURLWithPath: "/vm")
        #expect(configuration.resolve("disk.img", in: directory).path == "/vm/disk.img")
        #expect(configuration.resolve("/elsewhere/disk.img", in: directory).path == "/elsewhere/disk.img")
    }

    @Test func rejectsUnknownVersions() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try json.replacingOccurrences(of: "\"version\": 2", with: "\"version\": 9")
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

@Suite struct PortForwardTests {
    @Test func defaultsCoverSSHTheAPIAndEveryDisplay() {
        let names = PortForward.defaults.map(\.name)
        #expect(names.prefix(4) == ["ssh", "api", "vnc-operator", "vnc-10"])
        #expect(PortForward.defaults.first { $0.name == "ssh" }?.hostPort == 52022)
        #expect(PortForward.defaults.filter { $0.name.hasPrefix("vnc-") }.count == 17)
        #expect(Set(PortForward.defaults.map(\.hostPort)).count == PortForward.defaults.count)
    }
}
