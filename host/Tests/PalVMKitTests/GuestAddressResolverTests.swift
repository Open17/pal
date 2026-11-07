import Testing
@testable import PalVMKit

@Suite struct GuestAddressResolverTests {
    let leases = """
        {
        \tname=pal
        \tip_address=192.168.64.3
        \thw_address=1,2:a:3b:4c:5d:6e
        \tidentifier=1,2:a:3b:4c:5d:6e
        \tlease=0x6700aaaa
        }
        {
        \tname=pal
        \tip_address=192.168.64.7
        \thw_address=1,2:a:3b:4c:5d:6e
        \tidentifier=1,2:a:3b:4c:5d:6e
        \tlease=0x6700bbbb
        }
        {
        \tname=other
        \tip_address=192.168.64.9
        \thw_address=1,2:ff:ff:ff:ff:ff
        \tlease=0x6700cccc
        }
        """

    @Test func findsNewestLeaseForMAC() {
        #expect(GuestAddressResolver.address(for: "02:0a:3b:4c:5d:6e", inLeases: leases) == "192.168.64.7")
    }

    @Test func unknownMACHasNoAddress() {
        #expect(GuestAddressResolver.address(for: "02:00:00:00:00:00", inLeases: leases) == nil)
        #expect(GuestAddressResolver.address(for: "not-a-mac", inLeases: leases) == nil)
    }

    @Test func parsesAllCompleteLeases() {
        #expect(GuestAddressResolver.parseLeases(leases).count == 3)
        #expect(GuestAddressResolver.parseLeases("{\nip_address=1.2.3.4\n}").isEmpty)
    }
}
