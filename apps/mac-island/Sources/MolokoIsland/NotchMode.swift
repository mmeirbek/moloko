import AppKit
import CoreGraphics

/// MacBooks with a notch also offer "below the notch" display modes (for example 1512×945 next
/// to the default 1512×982): the strip with the notch is switched off and no app can draw
/// there, so the island cannot sit in the notch. This finds the matching mode that includes
/// the notch strip — same width and scale, the panel's full height — and switches to it.
enum NotchMode {
    /// A mode of the built-in display that shows the notch strip, when the current one hides it.
    static func notchModeAvailable() -> (display: CGDirectDisplayID, mode: CGDisplayMode)? {
        guard let screen = NSScreen.screens.first(where: { isBuiltIn($0) }), screen.safeAreaInsets.top == 0,
              let id = displayID(screen), let current = CGDisplayCopyDisplayMode(id) else { return nil }
        let options = [kCGDisplayShowDuplicateLowResolutionModes: true] as CFDictionary
        let modes = (CGDisplayCopyAllDisplayModes(id, options) as? [CGDisplayMode]) ?? []
        // Same width and scale, taller: the extra rows are the notch strip.
        let taller = modes.filter {
            $0.width == current.width && $0.pixelWidth == current.pixelWidth
                && $0.height > current.height && $0.isUsableForDesktopGUI()
        }
        let best = taller.min { a, b in
            // closest height, then the same refresh rate as now
            if a.height != b.height { return a.height < b.height }
            return abs(a.refreshRate - current.refreshRate) < abs(b.refreshRate - current.refreshRate)
        }
        return best.map { (id, $0) }
    }

    /// Switches like System Settings → Displays would (kept after restart). True on success.
    @discardableResult
    static func switchToNotchMode() -> Bool {
        guard let (id, mode) = notchModeAvailable() else { return false }
        var config: CGDisplayConfigRef?
        guard CGBeginDisplayConfiguration(&config) == .success else { return false }
        CGConfigureDisplayWithDisplayMode(config, id, mode, nil)
        let ok = CGCompleteDisplayConfiguration(config, .permanently) == .success
        Log.info("display mode \(mode.width)x\(mode.height): \(ok ? "switched" : "failed")")
        return ok
    }

    private static func displayID(_ screen: NSScreen) -> CGDirectDisplayID? {
        (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value
    }

    private static func isBuiltIn(_ screen: NSScreen) -> Bool {
        displayID(screen).map { CGDisplayIsBuiltin($0) != 0 } ?? false
    }
}
