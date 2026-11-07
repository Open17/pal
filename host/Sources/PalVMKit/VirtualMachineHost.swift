import Foundation
import Virtualization

/// Runs one virtual machine on the main queue and reports its lifecycle.
public final class VirtualMachineHost: NSObject, VZVirtualMachineDelegate {
    public enum State: String, Codable, Sendable {
        case starting, running, stopping, stopped, error
    }

    public private(set) var state: State = .stopped
    public private(set) var startedAt: Date?
    public private(set) var lastError: String?

    /// Called on the main queue when the guest has stopped for any reason.
    public var onStop: ((_ error: Error?) -> Void)?

    private let machine: VZVirtualMachine

    public init(configuration: VZVirtualMachineConfiguration) {
        self.machine = VZVirtualMachine(configuration: configuration, queue: .main)
        super.init()
        machine.delegate = self
    }

    /// The vsock device that carries all traffic to and from the guest.
    public var socketDevice: VZVirtioSocketDevice? {
        machine.socketDevices.first as? VZVirtioSocketDevice
    }

    public func start(completion: @escaping (Result<Void, Error>) -> Void) {
        dispatchPrecondition(condition: .onQueue(.main))
        state = .starting
        machine.start { [weak self] result in
            guard let self else { return }
            switch result {
            case .success:
                self.state = .running
                self.startedAt = Date()
            case .failure(let error):
                self.state = .error
                self.lastError = error.localizedDescription
            }
            completion(result)
        }
    }

    /// Ask the guest to shut down cleanly, then force it off after `timeout`.
    public func shutDown(timeout: TimeInterval = 90) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard state == .running || state == .starting else { return }
        state = .stopping
        do {
            try machine.requestStop()
        } catch {
            forceStop()
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { [weak self] in
            guard let self, self.state == .stopping else { return }
            self.forceStop()
        }
    }

    private func forceStop() {
        guard machine.canStop else { return }
        machine.stop { [weak self] error in
            self?.finish(error: error)
        }
    }

    private func finish(error: Error?) {
        guard state != .stopped else { return }
        state = error == nil ? .stopped : .error
        lastError = error?.localizedDescription
        onStop?(error)
    }

    // MARK: VZVirtualMachineDelegate

    public func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        finish(error: nil)
    }

    public func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        finish(error: error)
    }
}
