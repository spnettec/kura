/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.internal.linux.executor;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class UnprivilegedProcessIdentityTest {

    private static final String SAFE = "Name:\tjava\nUid:\t996\t996\t996\t996\n"
            + "Gid:\t989\t989\t989\t989\nGroups:\t20 989 997\n"
            + "CapInh:\t0000000000000000\nCapPrm:\t0000000000000000\n"
            + "CapEff:\t0000000000000000\nCapBnd:\t0000000000000000\n"
            + "CapAmb:\t0000000000000000\nNoNewPrivs:\t1\n";

    private boolean accepts(String status) {
        return UnprivilegedProcessIdentity.matches("kurad", "kurad", status, status);
    }

    @Test
    void acceptsOnlyTheSameKernelUsername() {
        assertTrue(accepts(SAFE));
        assertFalse(UnprivilegedProcessIdentity.matches("root", "kurad", SAFE, SAFE));
        assertFalse(UnprivilegedProcessIdentity.matches("kurad", "root", SAFE, SAFE));
        assertFalse(UnprivilegedProcessIdentity.matches("", "", SAFE, SAFE));
        assertFalse(UnprivilegedProcessIdentity.matches(null, "kurad", SAFE, SAFE));
        assertFalse(UnprivilegedProcessIdentity.matches("kurad", null, SAFE, SAFE));
    }

    @Test
    void rejectsEveryCapabilitySetAndMissingNnp() {
        for (String field : new String[] { "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb" }) {
            assertFalse(accepts(SAFE.replace(field + ":\t0000000000000000", field + ":\t0000000000000001")), field);
        }
        assertFalse(accepts(SAFE.replace("NoNewPrivs:\t1", "NoNewPrivs:\t0")));
    }

    @Test
    void rejectsRootSavedOrMismatchedIds() {
        for (String field : new String[] { "Uid", "Gid" }) {
            String original = field.equals("Uid") ? "996\t996\t996\t996" : "989\t989\t989\t989";
            for (String ids : new String[] { "0 0 0 0", "996 996 0 996", "996 996 996 0", "996 997 996 996",
                    "996 996 996", "996 996 996 996 996", "-1 -1 -1 -1", "4294967295 4294967295 4294967295 4294967295" }) {
                assertFalse(accepts(SAFE.replace(field + ":\t" + original, field + ":\t" + ids)), field + ":" + ids);
            }
        }
    }

    @Test
    void rejectsRootOrInvalidSupplementaryGroups() {
        for (String groups : new String[] { "0", "20 0 997", "-1", "989 junk", "4294967295", "999999999999999999" }) {
            assertFalse(accepts(SAFE.replace("20 989 997", groups)), groups);
        }
        assertTrue(accepts(SAFE.replace("20 989 997", "")));
    }

    @Test
    void rejectsMissingDuplicateAndMalformedFields() {
        for (String field : new String[] { "Uid", "Gid", "Groups", "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs" }) {
            assertFalse(accepts(SAFE.replaceAll("(?m)^" + field + ":.*\\n", "")), field);
            assertFalse(accepts(SAFE + field + ":\t0\n"), field);
        }
        for (String value : new String[] { "0", "000000000000000x", "-000000000000000", "00000000000000000" }) {
            assertFalse(accepts(SAFE.replace("CapEff:\t0000000000000000", "CapEff:\t" + value)), value);
        }
        assertFalse(accepts(null));
    }

    @Test
    void requiresThreadAndProcessLeaderIdentityToAgree() {
        assertFalse(UnprivilegedProcessIdentity.matches("kurad", "kurad", SAFE, SAFE.replace("996", "998")));
        assertFalse(UnprivilegedProcessIdentity.matches("kurad", "kurad", SAFE, SAFE.replace("20 989 997", "989 997")));
        assertFalse(UnprivilegedProcessIdentity.matches("kurad", "kurad", SAFE, SAFE.replace("NoNewPrivs:\t1", "NoNewPrivs:\t0")));
        assertTrue(UnprivilegedProcessIdentity.matches("kurad", "kurad", SAFE, SAFE.replace('\t', ' ')));
    }
}
