/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.net.firewall.transaction;
import java.util.Map;
import org.eclipse.kura.net.firewall.FirewallConfiguration;
/** One coherent confirmed view. Values are detached and private to the caller. */
public final class FirewallSnapshot {
    private final FirewallConfiguration ipv4;
    private final FirewallConfiguration ipv6;
    private final Map<String, Object> view;
    public FirewallSnapshot(FirewallConfiguration ipv4, FirewallConfiguration ipv6, Map<String, Object> view) {
        this.ipv4 = ipv4; this.ipv6 = ipv6; this.view = view;
    }
    public FirewallConfiguration getIpv4() { return this.ipv4; }
    public FirewallConfiguration getIpv6() { return this.ipv6; }
    public Map<String, Object> getView() { return this.view; }
}
