import Foundation
import Virtualization

/// Turns a `VMConfiguration` into a validated hypervisor configuration.
///
/// The guest is deliberately minimal: EFI boot, a virtio disk, entropy, a
/// serial console, and a vsock device. There is no network
/// interface — the guest reaches the internet only through palvmd's egress
/// service — and no graphics device; the desktop is served over VNC.
public struct VirtualMachineBuilder {
    public let configuration: VMConfiguration
    public let directory: URL

    public init(configuration: VMConfiguration, directory: URL) {
        self.configuration = configuration
        self.directory = directory
    }

    /// Build the configuration. Validation needs the virtualization
    /// entitlement, so only a signed palvmd can validate.
    public func build(validate: Bool = true) throws -> VZVirtualMachineConfiguration {
        let vm = VZVirtualMachineConfiguration()
        vm.cpuCount = clampedCPUCount
        vm.memorySize = try clampedMemorySize()
        vm.platform = try platform()
        vm.bootLoader = try bootLoader()
        vm.storageDevices = try storageDevices()
        vm.networkDevices = []
        vm.socketDevices = [VZVirtioSocketDeviceConfiguration()]
        vm.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
        if let console = try serialConsole() {
            vm.serialPorts = [console]
        }
        if validate {
            try vm.validate()
        }
        return vm
    }

    var clampedCPUCount: Int {
        min(
            max(configuration.cpuCount, VZVirtualMachineConfiguration.minimumAllowedCPUCount),
            VZVirtualMachineConfiguration.maximumAllowedCPUCount
        )
    }

    func clampedMemorySize() throws -> UInt64 {
        let bytes = configuration.memorySizeMiB * 1024 * 1024
        guard bytes >= VZVirtualMachineConfiguration.minimumAllowedMemorySize else {
            throw PalHostError.invalidConfiguration("memorySizeMiB is below the minimum")
        }
        return min(bytes, VZVirtualMachineConfiguration.maximumAllowedMemorySize)
    }

    private func url(_ path: String) -> URL {
        configuration.resolve(path, in: directory)
    }

    /// A stable machine identity so the guest sees the same hardware every boot.
    private func platform() throws -> VZGenericPlatformConfiguration {
        let platform = VZGenericPlatformConfiguration()
        let identifierURL = url(configuration.machineIdentifier)
        if let data = try? Data(contentsOf: identifierURL),
           let identifier = VZGenericMachineIdentifier(dataRepresentation: data) {
            platform.machineIdentifier = identifier
        } else {
            let identifier = VZGenericMachineIdentifier()
            try identifier.dataRepresentation.write(to: identifierURL, options: .atomic)
            platform.machineIdentifier = identifier
        }
        return platform
    }

    private func bootLoader() throws -> VZEFIBootLoader {
        let loader = VZEFIBootLoader()
        let storeURL = url(configuration.efiVariableStore)
        if FileManager.default.fileExists(atPath: storeURL.path) {
            loader.variableStore = VZEFIVariableStore(url: storeURL)
        } else {
            loader.variableStore = try VZEFIVariableStore(creatingVariableStoreAt: storeURL)
        }
        return loader
    }

    private func storageDevices() throws -> [VZStorageDeviceConfiguration] {
        let diskURL = url(configuration.diskImage)
        guard FileManager.default.fileExists(atPath: diskURL.path) else {
            throw PalHostError.missingDisk(diskURL.path)
        }
        // Explicitly cached with full synchronization. The automatic caching mode
        // corrupts ext4 in Linux guests: files silently change on disk, which
        // shows up as crashes, kernel memory errors, and I/O errors.
        let disk = try VZDiskImageStorageDeviceAttachment(
            url: diskURL, readOnly: false, cachingMode: .cached, synchronizationMode: .full
        )
        var devices: [VZStorageDeviceConfiguration] = [VZVirtioBlockDeviceConfiguration(attachment: disk)]
        if let seed = configuration.seedImage {
            let seedURL = url(seed)
            if FileManager.default.fileExists(atPath: seedURL.path) {
                let attachment = try VZDiskImageStorageDeviceAttachment(url: seedURL, readOnly: true)
                devices.append(VZVirtioBlockDeviceConfiguration(attachment: attachment))
            }
        }
        return devices
    }

    private func serialConsole() throws -> VZVirtioConsoleDeviceSerialPortConfiguration? {
        guard let log = configuration.consoleLog else { return nil }
        let console = VZVirtioConsoleDeviceSerialPortConfiguration()
        console.attachment = try VZFileSerialPortAttachment(url: url(log), append: true)
        return console
    }
}
