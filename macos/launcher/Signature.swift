// Is a downloaded LoupedeckBridge really one of the user's releases? (milestone 6)
//
// Accepted only if its code signature is valid under strict rules, it has the expected identifier, and the
// certificate that signed it is the one pinned in the running app (Info.plist LBSignerSHA256): the SHA-256 of
// that certificate (DER), the same value tools/install.sh compares. Not codesign's `certificate leaf = H"…"`
// requirement: that hash is SHA-1.

import CryptoKit
import Foundation
import Security

enum Signature {
    /// nil if `app` may be installed, otherwise why not, in plain words.
    static func problem(app: URL, identifier: String, pinnedSHA256: String) -> String? {
        let pinned = pinnedSHA256.lowercased()
        guard pinned.count == 64 else { return "this LoupedeckBridge has no pinned release key to check against" }

        var staticCode: SecStaticCode?
        guard SecStaticCodeCreateWithPath(app as CFURL, [], &staticCode) == errSecSuccess, let code = staticCode
        else { return "it isn't a signed app" }

        var requirement: SecRequirement?
        guard SecRequirementCreateWithString("identifier \"\(identifier)\"" as CFString, [], &requirement) == errSecSuccess
        else { return "couldn't build the signature requirement" }
        let strict = SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckAllArchitectures | kSecCSCheckNestedCode)
        var error: Unmanaged<CFError>?
        let status = SecStaticCodeCheckValidityWithErrors(code, strict, requirement, &error)
        guard status == errSecSuccess else {
            let why = error?.takeRetainedValue().localizedDescription ?? "error \(status)"
            return "its signature isn't valid for \(identifier) (\(why))"
        }

        guard let leaf = leafSHA256(code) else { return "it isn't signed with your LoupedeckBridge release key (no certificate)" }
        return leaf == pinned ? nil : "it isn't signed with your LoupedeckBridge release key"
    }

    /// The SHA-256 (lowercase hex) of the certificate that signed `code`, or nil (unsigned, or signed ad hoc).
    private static func leafSHA256(_ code: SecStaticCode) -> String? {
        var info: CFDictionary?
        guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
              let dict = info as? [String: Any],
              let certificates = dict[kSecCodeInfoCertificates as String] as? [SecCertificate],
              let leaf = certificates.first else { return nil }
        let der = SecCertificateCopyData(leaf) as Data
        return SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
    }
}
