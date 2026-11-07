import Foundation
import Testing
@testable import PalVMKit

@Suite struct LaunchAgentTests {
    @Test func propertyListKeepsDaemonAliveOnlyAfterCrashes() throws {
        let paths = PalPaths(root: URL(fileURLWithPath: "/tmp/pal-home"))
        let agent = LaunchAgent(executable: URL(fileURLWithPath: "/opt/pal/palvmd"), paths: paths)
        let plist = agent.propertyList()
        #expect(plist["Label"] as? String == "org.openpal.palvmd")
        #expect(plist["ProgramArguments"] as? [String] == ["/opt/pal/palvmd"])
        #expect((plist["KeepAlive"] as? [String: Bool])?["SuccessfulExit"] == false)
        #expect(plist["RunAtLoad"] as? Bool == true)
        #expect((plist["EnvironmentVariables"] as? [String: String])?["PAL_HOME"] == "/tmp/pal-home")
        _ = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
    }

    @Test func pathsHangOffTheRoot() {
        let paths = PalPaths(root: URL(fileURLWithPath: "/tmp/pal-home"))
        #expect(paths.vmConfiguration.path == "/tmp/pal-home/vm/config.json")
        #expect(paths.sshKey.path == "/tmp/pal-home/vm/secrets/id_ed25519")
        #expect(paths.controlSocket.path == "/tmp/pal-home/run/palvmd.sock")
    }
}
