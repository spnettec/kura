/*******************************************************************************
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *******************************************************************************/

package org.eclipse.kura.example.wire.math.singleport;

import java.util.ArrayDeque;

public class RunningAverage {

    private final ArrayDeque<Double> window;
    private final int windowSize;

    private double last;
    private double sum;

    public RunningAverage(final int windowSize) {
        this.window = new ArrayDeque<>(windowSize);
        this.windowSize = windowSize;
    }

    public double updateAndGet(double value) {
        if (this.window.size() >= this.windowSize) {
            this.last = this.window.removeFirst();
        }
        this.window.addLast(value);
        this.sum = value + this.sum - this.last;
        return this.sum / this.window.size();
    }

    public int getActualWindowSize() {
        return this.window.size();
    }
}
