import Foundation
import Testing

@testable import PalVMKit

@Suite struct SpliceTests {
    private func socketPair() -> (Int32, Int32) {
        var fds: [Int32] = [0, 0]
        #expect(socketpair(AF_UNIX, SOCK_STREAM, 0, &fds) == 0)
        return (fds[0], fds[1])
    }

    private func readAll(_ fd: Int32) -> Data {
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 65536)
        while true {
            let count = read(fd, &buffer, buffer.count)
            if count <= 0 { return data }
            data.append(contentsOf: buffer[0..<count])
        }
    }

    @Test func copiesEverythingBothWays() async {
        let (app, appSide) = socketPair()
        let (vmSide, vm) = socketPair()
        Splice.run(appSide, vmSide)
        let payload = Data((0..<3_000_000).map { UInt8($0 % 251) })
        Thread.detachNewThread {
            payload.withUnsafeBytes { _ = write(vm, $0.baseAddress!, $0.count) }
            shutdown(vm, SHUT_WR)
        }
        #expect(readAll(app) == payload)
        close(app)
        close(vm)
    }

    @Test func dropsAConnectionThatFallsTooFarBehind() async {
        // The app side never reads: the VM side is still read promptly, until
        // too much is waiting, and then the connection ends instead.
        let (app, appSide) = socketPair()
        let (vmSide, vm) = socketPair()
        Splice.run(appSide, vmSide, limit: 1_000_000)
        Sockets.noSigPipe(vm)
        let chunk = [UInt8](repeating: 7, count: 65536)
        var sent = 0
        while sent < 50_000_000 {
            let written = write(vm, chunk, chunk.count)
            if written <= 0 { break }
            sent += written
        }
        #expect(sent < 50_000_000)
        close(app)
        close(vm)
    }
}
