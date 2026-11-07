import Foundation
import Testing
@testable import PalVMKit

@Suite struct ControlTests {
    @Test func protocolRoundTrip() throws {
        let response = ControlResponse(
            ok: true, state: .running, address: "192.168.64.7", pid: 42,
            startedAt: Date(timeIntervalSince1970: 1_800_000_000)
        )
        let line = try ControlCoding.line(response)
        #expect(line.last == 0x0A)
        let decoded = try ControlCoding.decoder().decode(ControlResponse.self, from: line.dropLast())
        #expect(decoded == response)
        let request = try ControlCoding.line(ControlRequest(.stop))
        #expect(String(decoding: request, as: UTF8.self) == "{\"command\":\"stop\"}\n")
    }

    @Test func serverAnswersClient() async throws {
        let socket = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("palctl-\(UUID().uuidString.prefix(8)).sock")
        let server = ControlServer(socketURL: socket) { request, respond in
            respond(ControlResponse(ok: request.command == .status, state: .running))
        }
        try server.start()
        defer { server.stop() }

        let client = ControlClient(socketURL: socket)
        let response = try await Task.detached { try client.send(ControlRequest(.status)) }.value
        #expect(response == ControlResponse(ok: true, state: .running))
    }

    @Test func clientReportsNoDaemon() {
        let client = ControlClient(socketURL: URL(fileURLWithPath: "/tmp/pal-missing-\(UUID()).sock"))
        #expect(client.status() == nil)
    }
}
