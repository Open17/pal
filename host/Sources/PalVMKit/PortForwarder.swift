import Darwin
import Foundation
import Virtualization

/// Makes guest services reachable on 127.0.0.1 of this Mac.
///
/// Each forwarded port listens on loopback only, so nothing on the network
/// can reach the guest. Connections are carried to the guest agent over
/// vsock, which connects them to the same service inside the guest.
public final class PortForwarder {
    public private(set) var active: [PortForward] = []
    private let forwards: [PortForward]
    private let device: () -> VZVirtioSocketDevice?
    private let log: @Sendable (String) -> Void
    private var listeners: [Int32] = []

    /// `device` is called on the main queue.
    public init(
        forwards: [PortForward],
        device: @escaping () -> VZVirtioSocketDevice?,
        log: @escaping @Sendable (String) -> Void
    ) {
        self.forwards = forwards
        self.device = device
        self.log = log
    }

    public func start() {
        for forward in forwards {
            do {
                let listener = try Sockets.listenLoopback(port: forward.hostPort)
                listeners.append(listener)
                active.append(forward)
                Thread.detachNewThread { [self] in acceptLoop(listener, forward) }
            } catch {
                log("not forwarding \(forward.name): \(error)")
            }
        }
    }

    public func stop() {
        listeners.forEach { close($0) }
        listeners.removeAll()
        active.removeAll()
    }

    private func acceptLoop(_ listener: Int32, _ forward: PortForward) {
        while true {
            let client = accept(listener, nil, nil)
            if client < 0 {
                if errno == EINTR { continue }
                return  // listener closed
            }
            Sockets.noSigPipe(client)
            DispatchQueue.main.async { [self] in connect(client, to: forward) }
        }
    }

    private func connect(_ client: Int32, to forward: PortForward) {
        guard let device = device() else {
            close(client)
            return
        }
        device.connect(toPort: GuestChannel.inboundPort) { result in
            guard case .success(let connection) = result else {
                close(client)
                return
            }
            let guest = dup(connection.fileDescriptor)
            connection.close()
            guard guest >= 0 else {
                close(client)
                return
            }
            Thread.detachNewThread {
                Sockets.setTimeout(10, on: guest)
                do {
                    try Sockets.writeMessage(InboundRequest(port: forward.guestPort), to: guest)
                    let reply = try Sockets.readMessage(ChannelReply.self, from: guest)
                    guard reply.ok else { throw PalHostError.controlFailed(reply.error ?? "refused") }
                } catch {
                    close(guest)
                    close(client)
                    return
                }
                Sockets.clearTimeout(on: guest)
                Splice.run(client, guest)
            }
        }
    }
}
