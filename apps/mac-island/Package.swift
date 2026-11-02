// swift-tools-version: 5.10
// Moloko Island — a native macOS shell that shows moloko's `/island` page around the notch.
// Builds with the Command Line Tools only: `swift build -c release` (see scripts/bundle.sh).
// No third-party dependencies: AppKit, SwiftUI, WebKit and ServiceManagement only.
import PackageDescription

let package = Package(
    name: "MolokoIsland",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "MolokoIsland",
            path: "Sources/MolokoIsland"
        ),
    ]
)
