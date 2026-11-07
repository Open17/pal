import Foundation

/// Where Pal keeps its files on the Mac.
public struct PalPaths: Sendable {
    public let root: URL

    public init(root: URL? = nil) {
        if let root {
            self.root = root
        } else if let override = ProcessInfo.processInfo.environment["PAL_HOME"], !override.isEmpty {
            self.root = URL(fileURLWithPath: (override as NSString).expandingTildeInPath, isDirectory: true)
        } else {
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            self.root = support.appendingPathComponent("Pal", isDirectory: true)
        }
    }

    /// The VM bundle: disk, seed, firmware store, config, secrets.
    public var vmDirectory: URL { root.appendingPathComponent("vm", isDirectory: true) }
    public var vmConfiguration: URL { vmDirectory.appendingPathComponent("config.json") }
    public var secrets: URL { vmDirectory.appendingPathComponent("secrets", isDirectory: true) }
    public var sshKey: URL { secrets.appendingPathComponent("id_ed25519") }
    public var apiToken: URL { secrets.appendingPathComponent("api-token") }
    public var vncPassword: URL { secrets.appendingPathComponent("vnc-password") }

    public var runDirectory: URL { root.appendingPathComponent("run", isDirectory: true) }
    public var controlSocket: URL { runDirectory.appendingPathComponent("palvmd.sock") }

    public var binDirectory: URL { root.appendingPathComponent("bin", isDirectory: true) }

    public var logDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Pal", isDirectory: true)
    }
}
