// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "Pal",
    platforms: [.macOS(.v26)],
    dependencies: [
        .package(path: "../host"),
    ],
    targets: [
        .executableTarget(
            name: "Pal",
            dependencies: [.product(name: "PalVMKit", package: "host")],
            path: "Sources/Pal",
            swiftSettings: [.defaultIsolation(MainActor.self)]
        )
    ]
)
