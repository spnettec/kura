/*******************************************************************************
 * Copyright (c) 2016, 2020 Red Hat Inc and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.camel.runner;

import javax.script.ScriptException;
import javax.script.SimpleBindings;

import org.junit.Assert;
import org.junit.Test;

public class ScriptRunnerTest {

    /**
     * Test a simple call
     */
    @Test
    public void testScript1() throws ScriptException {
        final ScriptRunner runner = ScriptRunner.create(null, "JavaScript", "42;");

        final Object result = runner.run();

        Assert.assertTrue(result instanceof Number);
        Assert.assertEquals(42.0, ((Number) result).doubleValue(), 0.001);
    }

    /**
     * Test a call with arguments
     */
    @Test
    public void testScript2() throws ScriptException {
        final ScriptRunner runner = ScriptRunner.create(null, "JavaScript", "foo + 'bar';");

        SimpleBindings bindings = new SimpleBindings();
        bindings.put("foo", "bar");
        final Object result = runner.run(bindings);

        Assert.assertEquals("barbar", result);
    }
}
