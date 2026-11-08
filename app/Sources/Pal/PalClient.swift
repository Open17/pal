import Foundation
import PalVMKit

nonisolated struct PalError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

private nonisolated struct ErrorBody: Decodable {
    struct Detail: Decodable { let message: String }
    let error: Detail
}

/// Talks to the Pal runtime in the VM. palvmd forwards its API to this Mac's
/// loopback interface, and the token comes from the VM's secrets folder, so
/// there is nothing to configure.
final class PalClient {
    static let defaultURL = "http://127.0.0.1:8765"

    let baseURL: URL
    let token: String
    private let session: URLSession
    /// The event stream gets its own session so the long-lived socket never
    /// holds up ordinary requests.
    private let eventSession: URLSession
    private let decoder = JSONDecoder.pal()
    private let encoder = JSONEncoder()

    init(baseURL: URL, token: String) {
        self.baseURL = baseURL
        self.token = token
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        session = URLSession(configuration: config)
        eventSession = URLSession(configuration: .default)
    }

    /// The address from Settings (if changed), and the VM's API token.
    static func fromDefaults() -> PalClient {
        let defaults = UserDefaults.standard
        let raw = defaults.string(forKey: "serverURL")?.trimmingCharacters(in: .whitespaces) ?? ""
        let url = URL(string: raw.isEmpty ? defaultURL : raw) ?? URL(string: defaultURL)!
        let saved = defaults.string(forKey: "token")?.trimmingCharacters(in: .whitespaces) ?? ""
        return PalClient(baseURL: url, token: saved.isEmpty ? Secrets.apiToken ?? "" : saved)
    }

    var displayAddress: String {
        baseURL.host().map { host in baseURL.port.map { "\(host):\($0)" } ?? host } ?? baseURL.absoluteString
    }

    func get<T: Decodable>(_ path: String) async throws -> T {
        try decoder.decode(T.self, from: try await data("GET", path, nil))
    }

    func post<T: Decodable>(_ path: String, _ body: (any Encodable)? = nil) async throws -> T {
        try decoder.decode(T.self, from: try await data("POST", path, body))
    }

    func patch<T: Decodable>(_ path: String, _ body: any Encodable) async throws -> T {
        try decoder.decode(T.self, from: try await data("PATCH", path, body))
    }

    /// For calls whose response we don't need.
    func run(_ method: String, _ path: String, _ body: (any Encodable)? = nil) async throws {
        _ = try await data(method, path, body)
    }

    func eventsTask() -> URLSessionWebSocketTask {
        var comps = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        comps.scheme = comps.scheme == "https" ? "wss" : "ws"
        comps.path = "/v1/events"
        var request = URLRequest(url: comps.url!)
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return eventSession.webSocketTask(with: request)
    }

    func decodeEvent(_ data: Data) throws -> ServerEvent {
        try decoder.decode(ServerEvent.self, from: data)
    }

    private func data(_ method: String, _ path: String, _ body: (any Encodable)?) async throws -> Data {
        var base = baseURL.absoluteString
        if base.hasSuffix("/") { base.removeLast() }
        guard let url = URL(string: base + path) else { throw PalError(message: "The address in Settings isn't valid.") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.httpBody = try encoder.encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let message = (try? decoder.decode(ErrorBody.self, from: data))?.error.message ?? "Request failed (\(status))."
            throw PalError(message: message)
        }
        return data
    }
}

/// Secrets the image builder generated for this Mac's VM.
nonisolated enum Secrets {
    static var apiToken: String? { read(PalPaths().apiToken) }
    static var vncPassword: String? { read(PalPaths().vncPassword) }

    private static func read(_ url: URL) -> String? {
        let value = (try? String(contentsOf: url, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
        return value?.isEmpty == false ? value : nil
    }
}
