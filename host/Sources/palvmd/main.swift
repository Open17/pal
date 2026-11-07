// palvmd: runs the Pal virtual machine in the background.
//
// Started by launchd (see `palctl start`). It boots the VM described by
// vm/config.json, serves the control socket, and exits once the guest has
// shut down. A clean exit tells launchd not to restart it; a crash does.

import Darwin
import Foundation
import PalVMKit

setvbuf(stdout, nil, _IOLBF, 0)

let timestamp = ISO8601DateFormatter()
func log(_ message: String) {
    print("\(timestamp.string(from: Date())) palvmd: \(message)")
}

/// Exit without asking launchd to restart us: nothing will change until the
/// user fixes the problem.
func giveUp(_ message: String) -> Never {
    log(message)
    exit(0)
}

let paths = PalPaths()

if let running = ControlClient(paths: paths).status() {
    giveUp("already running (pid \(running.pid.map(String.init) ?? "unknown"))")
}

let configuration: VMConfiguration
let host: VirtualMachineHost
do {
    configuration = try VMConfiguration.load(from: paths.vmConfiguration)
    let built = try VirtualMachineBuilder(configuration: configuration, directory: paths.vmDirectory).build()
    host = VirtualMachineHost(configuration: built, macAddress: configuration.macAddress)
} catch let error as PalHostError {
    giveUp(error.description)
} catch {
    giveUp("invalid VM configuration: \(error.localizedDescription)")
}

let resolver = GuestAddressResolver()
let server = ControlServer(socketURL: paths.controlSocket) { request, respond in
    switch request.command {
    case .status:
        respond(
            ControlResponse(
                ok: true,
                state: host.state,
                address: resolver.address(for: host.macAddress),
                macAddress: host.macAddress,
                pid: getpid(),
                startedAt: host.startedAt,
                error: host.lastError
            )
        )
    case .stop:
        log("shutdown requested")
        respond(ControlResponse(ok: true, state: .stopping))
        host.shutDown()
    }
}

host.onStop = { error in
    server.stop()
    if let error {
        log("VM stopped with error: \(error.localizedDescription)")
        exit(1)
    }
    log("VM stopped")
    exit(0)
}

// launchd sends SIGTERM on bootout and at logout: shut the guest down cleanly.
var signalSources: [DispatchSourceSignal] = []
for signalNumber in [SIGTERM, SIGINT] {
    signal(signalNumber, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
    source.setEventHandler {
        log("received signal \(signalNumber); shutting down the guest")
        host.shutDown()
    }
    source.resume()
    signalSources.append(source)
}

do {
    try server.start()
} catch {
    log("cannot open control socket: \(error)")
    exit(1)
}

log("starting VM (\(configuration.cpuCount) CPUs, \(configuration.memorySizeMiB) MiB, MAC \(configuration.macAddress))")
host.start { result in
    switch result {
    case .success:
        log("VM running")
    case .failure(let error):
        log("VM failed to start: \(error.localizedDescription)")
        server.stop()
        exit(1)
    }
}

dispatchMain()
