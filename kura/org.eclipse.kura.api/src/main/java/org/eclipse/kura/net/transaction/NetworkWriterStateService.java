/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.net.transaction;

import org.eclipse.kura.KuraException;
import org.osgi.annotation.versioning.ProviderType;

/**
 * Optional local observation of durably suppressed legacy network and firewall writers.
 * This does not grant the observer system-write permission or migrate any rule.
 * @since 1.1.0
 */
@ProviderType
public interface NetworkWriterStateService {
    /**
     * Reject unless a durable local owner fence inhibits future legacy writes
     * and every participating in-flight legacy network/firewall operation has drained. No backend
     * or ownership state is changed. A missing service is not a quiescence proof.
     */
    void requireAgentQuiescent() throws KuraException;

    /** Read an existing legacy model without initialization,backend commands or file writes. */
    default java.util.List<LegacyFirewallFamily> observeLegacyFirewall() throws KuraException {
        throw new UnsupportedOperationException("UNSUPPORTED: original legacy firewall model observer");
    }

    /** Actual writer inputs. Ruleset text is data,never permission to execute it. */
    record LegacyFirewallFamily(String family, String instanceId, boolean allowIcmp, String expectedRuleset, String managedRuleset, java.util.Map<String,String> modelProperties,
            java.util.List<AutomaticNat> automaticNat, java.util.Map<String, java.util.List<String>> additionalRules,
            java.util.List<String> runtimeNatRuleTypes, java.util.List<Integer> runtimePortForwardDestinationPrefixes) {
        /** Older observers carry no runtime type evidence; null is never an IP_FORWARDING assertion. */
        public LegacyFirewallFamily(String family,String instanceId,boolean allowIcmp,String expectedRuleset,String managedRuleset,
                java.util.Map<String,String> modelProperties,java.util.List<AutomaticNat> automaticNat,
                java.util.Map<String,java.util.List<String>> additionalRules) {
            this(family,instanceId,allowIcmp,expectedRuleset,managedRuleset,modelProperties,automaticNat,additionalRules,null,null);
        }
        /** Unpublished 1.3 candidate callers retain their original nine-argument ABI. */
        public LegacyFirewallFamily(String family,String instanceId,boolean allowIcmp,String expectedRuleset,String managedRuleset,
                java.util.Map<String,String> modelProperties,java.util.List<AutomaticNat> automaticNat,
                java.util.Map<String,java.util.List<String>> additionalRules,java.util.List<String> runtimeNatRuleTypes) {
            this(family,instanceId,allowIcmp,expectedRuleset,managedRuleset,modelProperties,automaticNat,additionalRules,runtimeNatRuleTypes,null);
        }
        public LegacyFirewallFamily {
            java.util.Objects.requireNonNull(family);java.util.Objects.requireNonNull(instanceId);
            java.util.Objects.requireNonNull(expectedRuleset);java.util.Objects.requireNonNull(managedRuleset);modelProperties=java.util.Map.copyOf(modelProperties);automaticNat=java.util.List.copyOf(automaticNat);
            additionalRules=additionalRules.entrySet().stream().collect(java.util.stream.Collectors.toUnmodifiableMap(
                    java.util.Map.Entry::getKey,entry->java.util.List.copyOf(entry.getValue())));
            if(runtimeNatRuleTypes!=null) {
                runtimeNatRuleTypes=java.util.List.copyOf(runtimeNatRuleTypes);
                if(runtimeNatRuleTypes.size()>4096||runtimeNatRuleTypes.stream().anyMatch(v->!java.util.Set.of("GENERIC","IP_FORWARDING","PORT_FORWARDING").contains(v)))
                    throw new IllegalArgumentException("CONFLICT: original runtime NAT rule types");
            }
            if(runtimePortForwardDestinationPrefixes!=null) {
                runtimePortForwardDestinationPrefixes=java.util.List.copyOf(runtimePortForwardDestinationPrefixes);
                int maximum="ipv4".equals(family)?32:128;
                if(runtimePortForwardDestinationPrefixes.size()>4096||runtimePortForwardDestinationPrefixes.stream().anyMatch(v->v<0||v>maximum))
                    throw new IllegalArgumentException("CONFLICT: original runtime destination prefixes");
            }
        }
    }
    record AutomaticNat(String sourceInterface, String destinationInterface, boolean masquerade) {
        public AutomaticNat {java.util.Objects.requireNonNull(sourceInterface);java.util.Objects.requireNonNull(destinationInterface);}
    }

}
