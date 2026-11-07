import Foundation

/// The VM definition written by the image builder (`vm/config.json`).
///
/// Paths are relative to the VM directory unless absolute.
public struct VMConfiguration: Codable, Equatable, Sendable {
    public static let currentVersion = 1

    public var version: Int
    public var cpuCount: Int
    public var memorySizeMiB: UInt64
    public var diskImage: String
    public var seedImage: String?
    public var efiVariableStore: String
    public var machineIdentifier: String
    public var macAddress: String
    public var consoleLog: String?

    public init(
        cpuCount: Int = 4,
        memorySizeMiB: UInt64 = 8192,
        diskImage: String = "disk.img",
        seedImage: String? = "seed.iso",
        efiVariableStore: String = "efi-vars.fd",
        machineIdentifier: String = "machine-id",
        macAddress: String,
        consoleLog: String? = "console.log"
    ) {
        self.version = Self.currentVersion
        self.cpuCount = cpuCount
        self.memorySizeMiB = memorySizeMiB
        self.diskImage = diskImage
        self.seedImage = seedImage
        self.efiVariableStore = efiVariableStore
        self.machineIdentifier = machineIdentifier
        self.macAddress = macAddress
        self.consoleLog = consoleLog
    }

    public static func load(from url: URL) throws -> VMConfiguration {
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            throw PalHostError.missingConfiguration(url.path)
        }
        let configuration = try JSONDecoder().decode(VMConfiguration.self, from: data)
        guard configuration.version == currentVersion else {
            throw PalHostError.unsupportedConfiguration(version: configuration.version)
        }
        return configuration
    }

    /// Resolve a configured path against the VM directory.
    public func resolve(_ path: String, in directory: URL) -> URL {
        path.hasPrefix("/")
            ? URL(fileURLWithPath: path)
            : directory.appendingPathComponent(path)
    }
}

public enum PalHostError: Error, CustomStringConvertible, Equatable {
    case missingConfiguration(String)
    case unsupportedConfiguration(version: Int)
    case missingDisk(String)
    case invalidMACAddress(String)
    case invalidConfiguration(String)
    case notRunning
    case controlFailed(String)
    case launchctlFailed(command: String, status: Int32, output: String)

    public var description: String {
        switch self {
        case .missingConfiguration(let path):
            return "no VM configuration at \(path); build the VM with guest/image/build-image.sh"
        case .unsupportedConfiguration(let version):
            return "VM configuration version \(version) is not supported"
        case .missingDisk(let path):
            return "no VM disk at \(path)"
        case .invalidMACAddress(let value):
            return "invalid MAC address \(value)"
        case .invalidConfiguration(let reason):
            return "invalid VM configuration: \(reason)"
        case .notRunning:
            return "the VM is not running"
        case .controlFailed(let reason):
            return "could not reach palvmd: \(reason)"
        case .launchctlFailed(let command, let status, let output):
            return "launchctl \(command) failed (\(status)): \(output)"
        }
    }
}
