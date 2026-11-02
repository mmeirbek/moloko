import AppKit
import SwiftUI

/// Small window that asks for the moloko address (first launch and "Сменить адрес moloko…").
@MainActor
final class SetupWindowController: NSObject, NSWindowDelegate {
    var onSave: ((URL) -> Void)?
    var onQuit: (() -> Void)?
    var onClose: (() -> Void)?

    private var window: NSWindow?

    var isVisible: Bool { window?.isVisible ?? false }

    func show(current: URL?, firstRun: Bool) {
        let form = SetupForm(
            initialAddress: current?.absoluteString ?? "",
            firstRun: firstRun,
            onSave: { [weak self] url in
                self?.onSave?(url)
                self?.window?.close()
            },
            onCancel: { [weak self] in
                if firstRun { self?.onQuit?() } else { self?.window?.close() }
            }
        )
        let host = NSHostingController(rootView: form)
        if let window {
            window.contentViewController = host
        } else {
            let window = NSWindow(contentViewController: host)
            window.styleMask = [.titled, .closable]
            window.title = "Moloko Island"
            window.isReleasedWhenClosed = false
            window.level = .floating
            window.delegate = self
            self.window = window
        }
        window?.center()
        NSApp.activate()
        window?.makeKeyAndOrderFront(nil)
        Log.info("address window shown (first run: \(firstRun))")
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }
}

private struct SetupForm: View {
    let firstRun: Bool
    let onSave: (URL) -> Void
    let onCancel: () -> Void

    @State private var address: String
    @State private var error: String?
    @FocusState private var focused: Bool

    init(initialAddress: String, firstRun: Bool, onSave: @escaping (URL) -> Void, onCancel: @escaping () -> Void) {
        self.firstRun = firstRun
        self.onSave = onSave
        self.onCancel = onCancel
        _address = State(initialValue: initialAddress)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 14) {
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable()
                    .frame(width: 52, height: 52)
                VStack(alignment: .leading, spacing: 4) {
                    Text(firstRun ? "Добро пожаловать в Moloko Island" : "Адрес moloko")
                        .font(.headline)
                    Text("Остров показывает ваш moloko у выреза экрана: офис агентов, одобрения, сохранённые агенты.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Адрес moloko").font(.subheadline.weight(.medium))
                TextField("https://имя.ts.net", text: $address)
                    .textFieldStyle(.roundedBorder)
                    .focused($focused)
                    .onSubmit(save)
                    .onChange(of: address) { error = nil }
                if let error {
                    Text(error).font(.caption).foregroundStyle(.red)
                } else {
                    Text("Например https://moloko.tail1234.ts.net или http://192.168.1.10:3000")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            HStack {
                Spacer()
                Button(firstRun ? "Выйти" : "Отмена", action: onCancel)
                    .keyboardShortcut(.cancelAction)
                Button("Сохранить", action: save)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 440)
        .onAppear { focused = true }
    }

    private func save() {
        guard let url = ServerAddress.normalize(address) else {
            error = "Нужен адрес вида https://имя.ts.net (http или https)."
            return
        }
        onSave(url)
    }
}
