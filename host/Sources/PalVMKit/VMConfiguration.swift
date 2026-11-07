import Foundation

/// The VM definition written by the image builder (`vm/config.json`).
///
/// Paths are relative to the VM directory unless absolute. The guest has no
/// network interface; `forwardedPorts` lists the guest services reachable on
/// this Mac's loopback interface.
public struct VMConfiguration: Codable, Equatable, Sendable {
    public static let currentVersion = 2

    public var version: Int
    public var cpuCount: Int
    public var memorySizeMiB: UInt64
    public var diskImage: String
    public var seedImage: String?
    public var efiVariableStore: String
    public var machineIdentifier: String
    public var consoleLog: String?
    public var forwardedPorts: [PortForward]

    public init(
        cpuCount: Int = 4,
        memorySizeMiB: UInt64 = 8192,
        diskImage: String = "disk.img",
        seedImage: String? = "seed.iso",
        efiVariableStore: String = "efi-vars.fd",
        machineIdentifier: String = "machine-id",
        consoleLog: String? = "console.log",
        forwardedPorts: [PortForward] = PortForward.defaults
    ) {
        self.version = Self.currentVersion
        self.cpuCount = cpuCount
        self.memorySizeMiB = memorySizeMiB
        self.diskImage = diskImage
        self.seedImage = seedImage
        self.efiVariableStore = efiVariableStore
        self.machineIdentifier = machineIdentifier
        self.consoleLog = consoleLog
        self.forwardedPorts = forwardedPorts
    }

    private enum CodingKeys: String, CodingKey {
        case version, cpuCount, memorySizeMiB, diskImage, seedImage, efiVariableStore
        case machineIdentifier, consoleLog, forwardedPorts
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        version = try container.decode(Int.self, forKey: .version)
        cpuCount = try container.decode(Int.self, forKey: .cpuCount)
        memorySizeMiB = try container.decode(UInt64.self, forKey: .memorySizeMiB)
        diskImage = try container.decode(String.self, forKey: .diskImage)
        seedImage = try container.decodeIfPresent(String.self, forKey: .seedImage)
        efiVariableStore = try container.decode(String.self, forKey: .efiVariableStore)
        machineIdentifier = try container.decode(String.self, forKey: .machineIdentifier)
        consoleLog = try container.decodeIfPresent(String.self, forKey: .consoleLog)
        forwardedPorts = try container.decodeIfPresent([PortForward].self, forKey: .forwardedPorts)
            ?? PortForward.defaults
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
    case invalidConfiguration(String)
    case notRunning
    case controlFailed(String)
    case launchctlFailed(command: String, status: Int32, output: String)

    public var description: String {
        switch self {
        case .missingConfiguration(let path):
            return "no VM configuration at \(path); build the VM with guest/image/build-image.sh"
        case .unsupportedConfiguration(let version):
            return "VM configuration version \(version) is not supported; rebuild it with "
                + "guest/image/build-image.sh --refresh-seed"
        case .missingDisk(let path):
            return "no VM disk at \(path)"
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
