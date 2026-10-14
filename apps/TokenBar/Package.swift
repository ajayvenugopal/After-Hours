// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TokenBar",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "TokenBar", targets: ["TokenBar"])],
    targets: [
        .target(name: "UsageCore"),
        .executableTarget(name: "TokenBar", dependencies: ["UsageCore"]),
        .testTarget(name: "UsageCoreTests", dependencies: ["UsageCore"])
    ]
)
