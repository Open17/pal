import Testing
@testable import PalVMKit

@Suite struct EgressPolicyTests {
    let mac = IPAddress("203.0.114.10")!
    var policy: EgressPolicy {
        let mac = self.mac
        return EgressPolicy(localAddresses: { [mac] })
    }

    @Test(arguments: [
        "1.1.1.1", "93.184.216.34", "151.101.1.69", "8.8.4.4",
        "2606:4700:4700::1111", "2a00:1450:4001:82a::200e",
    ])
    func publicAddressesAreAllowed(_ literal: String) throws {
        #expect(policy.decide(try #require(IPAddress(literal))) == .allow)
    }

    @Test(arguments: [
        "127.0.0.1", "10.1.2.3", "172.20.0.1", "192.168.64.1", "192.168.1.1",
        "169.254.169.254", "100.100.100.100", "0.0.0.0", "224.0.0.251", "255.255.255.255",
        "::1", "::", "fe80::1", "fd12:3456::1", "ff02::fb",
        "::ffff:192.168.1.1", "::ffff:127.0.0.1", "64:ff9b::a00:1", "2002:c0a8:101::1",
        "2001:db8::1", "2001::1",
    ])
    func privateAndSpecialAddressesAreRefused(_ literal: String) throws {
        #expect(!policy.decide(try #require(IPAddress(literal))).isAllowed)
    }

    @Test func thisMacIsRefusedEvenWithAPublicAddress() {
        #expect(policy.decide(mac) == .deny("an address of this Mac"))
    }

    @Test func embeddedPublicAddressesAreAllowed() throws {
        #expect(policy.decide(try #require(IPAddress("::ffff:1.1.1.1"))) == .allow)
    }

    @Test func parsingAndPrinting() {
        #expect(IPAddress("192.168.64.1")?.description == "192.168.64.1")
        #expect(IPAddress("2606:4700::1")?.description == "2606:4700::1")
        #expect(IPAddress("example.com") == nil)
        #expect(IPAddress("999.1.1.1") == nil)
    }

    @Test func realInterfacesIncludeLoopback() {
        #expect(IPAddress.localInterfaceAddresses().contains(IPAddress("127.0.0.1")!))
    }
}
