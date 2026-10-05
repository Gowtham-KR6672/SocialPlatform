import UIKit
import WebKit
import Capacitor

/// The app's web view, with zooming turned off on every page it loads.
/// iOS zooms in when a text box under 16px is tapped (the sign-in fields) and never zooms
/// back out, so every screen after that is a little too wide and slides left and right.
/// viewport-fit=cover lets the page read the home-bar height, so the phone menu sits above it.
class AppViewController: CAPBridgeViewController {
    // Added here (not in webViewConfiguration) because Capacitor swaps in its own script
    // list after that; this runs once the web view exists and before the first page loads.
    override func capacitorDidLoad() {
        super.capacitorDidLoad()
        let noZoom = """
        (function(){
          var m = document.querySelector('meta[name="viewport"]');
          if(!m){ m = document.createElement('meta'); m.name = 'viewport'; document.head.appendChild(m); }
          m.setAttribute('content', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover');
        })();
        """
        webView?.configuration.userContentController.addUserScript(
            WKUserScript(source: noZoom, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
    }
}

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = AppViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}
