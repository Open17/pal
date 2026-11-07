// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "PalHost",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "PalVMKit", targets: ["PalVMKit"]),
        .executable(name: "palvmd", targets: ["palvmd"]),
        .executable(name: "palctl", targets: ["palctl"]),
    ],
    targets: [
        .target(name: "PalVMKit"),
        .executableTarget(name: "palvmd", dependencies: ["PalVMKit"]),
        .executableTarget(name: "palctl", dependencies: ["PalVMKit"]),
        .testTarget(name: "PalVMKitTests", dependencies: ["PalVMKit"]),
    ],
    swiftLanguageModes: [.v5]
)
