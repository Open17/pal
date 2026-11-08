import Foundation
import Observation
import PalVMKit

/// Turns Pal's computer (the VM) on and off and reports its state.
///
/// palvmd runs the VM as a background launchd agent, so it keeps running when
/// this app quits and stays off once turned off. This only talks to palvmd's
/// control socket and to launchd.
@Observable
final class VMController {
    enum Power: Equatable {
        case unknown, off, starting, running, stopping
        case notInstalled(String)
    }

    private(set) var power: Power = .unknown
    private(set) var forwardedPorts: [PortForward] = []
    private(set) var startedAt: Date?
    var problem: String?

    @ObservationIgnored private let paths = PalPaths()
    @ObservationIgnored private var polling: Task<Void, Never>?

    var daemon: URL { paths.binDirectory.appendingPathComponent("palvmd") }
    var log: URL { paths.logDirectory.appendingPathComponent("palvmd.log") }

    var isRunning: Bool { power == .running }

    func startPolling() {
        guard polling == nil else { return }
        polling = Task {
            while !Task.isCancelled {
                await refresh()
                try? await Task.sleep(for: .seconds(power == .running ? 5 : 2))
            }
        }
    }

    func refresh() async {
        let paths = paths
        let daemon = daemon
        let status = await Task.detached { ControlClient(paths: paths).status() }.value
        if let status {
            forwardedPorts = status.forwardedPorts ?? []
            startedAt = status.startedAt
            switch status.state {
            case .stopping?: power = .stopping
            case .starting?: power = .starting
            default: if power != .stopping { power = .running }
            }
        } else if power != .starting {
            forwardedPorts = []
            startedAt = nil
            if !FileManager.default.isExecutableFile(atPath: daemon.path) {
                power = .notInstalled("Build the host tools with host/scripts/build.sh.")
            } else if !FileManager.default.fileExists(atPath: paths.vmConfiguration.path) {
                power = .notInstalled("Build the VM with guest/image/build-image.sh.")
            } else {
                power = .off
            }
        }
    }

    /// Turn the VM on. It keeps running in the background until turned off.
    func turnOn() {
        problem = nil
        power = .starting
        let agent = LaunchAgent(executable: daemon, paths: paths)
        Task {
            do {
                try await Task.detached { try agent.start() }.value
            } catch {
                problem = "\(error)"
                power = .off
            }
            await refresh()
        }
    }

    /// Shut the VM down cleanly and keep it off.
    func turnOff() {
        problem = nil
        power = .stopping
        let agent = LaunchAgent(executable: daemon, paths: paths)
        let client = ControlClient(paths: paths)
        Task {
            await Task.detached { Self.shutDown(agent: agent, client: client) }.value
            power = .off
            await refresh()
        }
    }

    /// Disable the agent, ask the guest to shut down, wait, then unload.
    private nonisolated static func shutDown(agent: LaunchAgent, client: ControlClient) {
        try? agent.disable()
        _ = try? client.send(ControlRequest(.stop))
        for _ in 0..<150 where client.status() != nil {
            Thread.sleep(forTimeInterval: 1)
        }
        try? agent.unload()
    }

    /// The Mac-side port for a guest port, e.g. a display's VNC port.
    func hostPort(forGuestPort port: Int) -> Int? {
        forwardedPorts.first { Int($0.guestPort) == port }.map { Int($0.hostPort) }
    }
}
