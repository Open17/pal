// palctl: turn the Pal VM on and off and inspect it.

import Darwin
import Foundation
import PalVMKit

let usage = """
    usage: palctl <command> [--daemon PATH]

    commands:
      start       turn the VM on (it keeps running in the background)
      stop        shut the VM down and keep it off
      status      show whether the VM is running and its address
      address     print the VM's IP address
      ssh [ARGS]  open a shell in the VM as the pal user
      uninstall   stop the VM and remove the launchd agent

    options:
      --daemon PATH   palvmd executable (default: next to palctl)
    """

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data("palctl: \(message)\n".utf8))
    exit(code)
}

var arguments = Array(CommandLine.arguments.dropFirst())
var daemonPath: String?
if let index = arguments.firstIndex(of: "--daemon") {
    guard index + 1 < arguments.count else { fail("--daemon needs a path", code: 2) }
    daemonPath = arguments[index + 1]
    arguments.removeSubrange(index...(index + 1))
}
guard let command = arguments.first else {
    print(usage)
    exit(2)
}

let paths = PalPaths()
let client = ControlClient(paths: paths)
let daemon: URL = daemonPath.map { URL(fileURLWithPath: $0) }
    ?? URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        .deletingLastPathComponent().appendingPathComponent("palvmd")
let agent = LaunchAgent(executable: daemon, paths: paths)

/// Poll until `condition` holds or `timeout` passes.
func wait(timeout: TimeInterval, until condition: () -> Bool) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if condition() { return true }
        usleep(500_000)
    }
    return condition()
}

func waitForAddress(timeout: TimeInterval) -> String? {
    var address: String?
    _ = wait(timeout: timeout) {
        address = client.status()?.address
        return address != nil
    }
    return address
}

func start() {
    guard FileManager.default.isExecutableFile(atPath: daemon.path) else {
        fail("palvmd not found at \(daemon.path); build it with host/scripts/build.sh")
    }
    guard FileManager.default.fileExists(atPath: paths.vmConfiguration.path) else {
        fail("no VM at \(paths.vmDirectory.path); build it with guest/image/build-image.sh")
    }
    if let status = client.status() {
        print("already running (\(status.state?.rawValue ?? "unknown"))")
        return
    }
    do {
        try agent.start()
    } catch {
        fail("\(error)")
    }
    guard wait(timeout: 30, until: { client.status() != nil }) else {
        fail("palvmd did not start; see \(paths.logDirectory.path)/palvmd.log")
    }
    print("VM started")
    if let address = waitForAddress(timeout: 60) {
        print("address: \(address)")
    } else {
        print("waiting for the guest network; run `palctl status` in a moment")
    }
}

func stop() {
    try? agent.disable()
    if client.status() != nil {
        _ = try? client.send(ControlRequest(.stop))
        print("shutting down…")
        if !wait(timeout: 150, until: { client.status() == nil }) {
            print("guest did not shut down in time; stopping it")
        }
    }
    do {
        try agent.unload()
    } catch {
        fail("\(error)")
    }
    print("VM off")
}

func status() {
    guard let status = client.status() else {
        print("off")
        exit(3)
    }
    print("state:   \(status.state?.rawValue ?? "unknown")")
    print("address: \(status.address ?? "(waiting for network)")")
    if let mac = status.macAddress { print("mac:     \(mac)") }
    if let pid = status.pid { print("pid:     \(pid)") }
    if let started = status.startedAt {
        print("since:   \(ISO8601DateFormatter().string(from: started))")
    }
    if let error = status.error { print("error:   \(error)") }
}

func ssh(_ extra: [String]) -> Never {
    guard let address = client.status()?.address else { fail("the VM is not running or has no address yet") }
    let knownHosts = paths.vmDirectory.appendingPathComponent("known_hosts").path
    let argv = [
        "/usr/bin/ssh", "-i", paths.sshKey.path,
        "-o", "UserKnownHostsFile=\(knownHosts)",
        "-o", "StrictHostKeyChecking=accept-new",
        "pal@\(address)",
    ] + extra
    let cArgs = argv.map { strdup($0) } + [nil]
    execv(argv[0], cArgs)
    fail("could not run ssh: \(String(cString: strerror(errno)))")
}

switch command {
case "start":
    start()
case "stop":
    stop()
case "status":
    status()
case "address":
    guard let address = client.status()?.address else { fail("no address (is the VM running?)", code: 3) }
    print(address)
case "ssh":
    ssh(Array(arguments.dropFirst()))
case "uninstall":
    stop()
    try? agent.uninstall()
    print("launchd agent removed")
case "-h", "--help", "help":
    print(usage)
default:
    print(usage)
    exit(2)
}
