# Google Play / VPN compliance notes

TunnelPilot's primary function is VPN connectivity. The app uses Android `VpnService` to create an encrypted tunnel to a remote WireGuard gateway.

Before Play submission:

- complete the current VpnService declaration in Play Console;
- clearly disclose VpnService use in the store listing;
- document what traffic is routed and why;
- encrypt traffic from the device to the VPN endpoint;
- do not redirect or manipulate traffic from other apps for monetization;
- keep ads and analytics inside the TunnelPilot app experience;
- complete the current Data safety and privacy disclosures.

Rewarded advertising, if added, will be opt-in and will grant an in-app reward. It will not be tied to modifying other applications' network traffic.
