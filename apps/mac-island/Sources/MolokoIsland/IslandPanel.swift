import AppKit

/// Borderless, non-activating panel that floats above the menu bar on every Space
/// (including full-screen apps). It may become key only while expanded, so that the
/// login form in the page can receive typing without activating the app.
final class IslandPanel: NSPanel {
    var allowsKey = false
    var onEscape: (() -> Void)?

    init(frame: CGRect) {
        super.init(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isFloatingPanel = true
        level = .statusBar // above the menu bar (24), below pop-up menus (101)
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false // the island draws its own shadow
        hidesOnDeactivate = false
        isMovable = false
        isReleasedWhenClosed = false
        acceptsMouseMovedEvents = true
        animationBehavior = .none
        becomesKeyOnlyIfNeeded = false
        appearance = NSAppearance(named: .darkAqua)
    }

    override var canBecomeKey: Bool { allowsKey }
    override var canBecomeMain: Bool { false }

    /// Borderless windows must be allowed to sit over the menu bar.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }

    /// Escape that the page did not handle travels up the responder chain to here.
    override func cancelOperation(_ sender: Any?) {
        onEscape?()
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 { // Escape
            onEscape?()
        } else {
            super.keyDown(with: event)
        }
    }
}
