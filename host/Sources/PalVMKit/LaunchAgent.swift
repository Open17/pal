import Foundation

/// Installs and controls palvmd as a per-user launchd agent.
///
/// Turning the VM on enables and bootstraps the agent; launchd then keeps it
/// running in the background, independent of any app, and restarts it if it
/// crashes. Turning it off disables the agent so it stays off — including
/// across logins — until it is turned on again.
public struct LaunchAgent: Sendable {
    public static let label = "org.openpal.palvmd"

    public let executable: URL
    public let paths: PalPaths

    public init(executable: URL, paths: PalPaths = PalPaths()) {
        self.executable = executable
        self.paths = paths
    }

    public var plistURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(Self.label).plist")
    }

    private var domain: String { "gui/\(getuid())" }
    private var service: String { "\(domain)/\(Self.label)" }

    public func propertyList() -> [String: Any] {
        let log = paths.logDirectory.appendingPathComponent("palvmd.log").path
        return [
            "Label": Self.label,
            "ProgramArguments": [executable.path],
            "EnvironmentVariables": ["PAL_HOME": paths.root.path],
            "RunAtLoad": true,
            // Restart after a crash, but not after a requested shutdown.
            "KeepAlive": ["SuccessfulExit": false],
            "ProcessType": "Interactive",
            "StandardOutPath": log,
            "StandardErrorPath": log,
            "ThrottleInterval": 10,
            // Give the guest time to shut down cleanly when the agent is unloaded.
            "ExitTimeOut": 120,
        ]
    }

    public func install() throws {
        try FileManager.default.createDirectory(
            at: plistURL.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(at: paths.logDirectory, withIntermediateDirectories: true)
        let data = try PropertyListSerialization.data(
            fromPropertyList: propertyList(), format: .xml, options: 0
        )
        try data.write(to: plistURL, options: .atomic)
    }

    public var isInstalled: Bool { FileManager.default.fileExists(atPath: plistURL.path) }

    public var isLoaded: Bool { (try? launchctl(["print", service])) != nil }

    /// Turn the VM on. Call only while palvmd isn't running.
    public func start() throws {
        try install()
        try launchctl(["enable", service])
        // launchd keeps the definition it loaded: reload it, or a changed one
        // (say, palvmd installed somewhere else) would be ignored.
        if isLoaded {
            try launchctl(["bootout", service])
        }
        try launchctl(["bootstrap", domain, plistURL.path])
        try launchctl(["kickstart", service])
    }

    /// Mark the VM as off so launchd will not start it again.
    public func disable() throws {
        try launchctl(["disable", service])
    }

    /// Unload the agent once palvmd has exited.
    public func unload() throws {
        if isLoaded {
            try launchctl(["bootout", service])
        }
    }

    public func uninstall() throws {
        try? disable()
        try? unload()
        if isInstalled {
            try FileManager.default.removeItem(at: plistURL)
        }
    }

    @discardableResult
    private func launchctl(_ arguments: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = arguments
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        let output = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw PalHostError.launchctlFailed(
                command: arguments.first ?? "",
                status: process.terminationStatus,
                output: output.trimmingCharacters(in: .whitespacesAndNewlines)
            )
        }
        return output
    }
}
