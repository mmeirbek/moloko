import Foundation
import os

/// Unified logging (`log stream --predicate 'subsystem == "kz.moloko.island"'`).
/// Never log cookies, tokens or page contents — only state changes and errors.
enum Log {
    /// `MOLOKO_ISLAND_DEBUG=1` mirrors logs to stdout and enables `DebugCommands`.
    static let debugEnabled = ProcessInfo.processInfo.environment["MOLOKO_ISLAND_DEBUG"] == "1"

    private static let logger = Logger(subsystem: "kz.moloko.island", category: "island")

    static func info(_ message: String) {
        logger.notice("\(message, privacy: .public)")
        mirror("info", message)
    }

    static func error(_ message: String) {
        logger.error("\(message, privacy: .public)")
        mirror("error", message)
    }

    private static func mirror(_ level: String, _ message: String) {
        guard debugEnabled else { return }
        print("[island] \(level): \(message)")
        fflush(stdout)
    }
}
