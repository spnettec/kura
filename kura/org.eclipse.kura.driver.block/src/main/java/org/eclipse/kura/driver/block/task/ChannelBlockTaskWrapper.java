/*******************************************************************************
 * Copyright (c) 2017, 2020 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.driver.block.task;

public abstract class ChannelBlockTaskWrapper extends ChannelBlockTask {

    private final ChannelBlockTask wrapped;

    public ChannelBlockTaskWrapper(final ChannelBlockTask wrapped) {
        super(wrapped.getRecord(), wrapped.getStart(), wrapped.getEnd(), wrapped.getMode());
        this.wrapped = wrapped;
    }

    public ChannelBlockTask getWrappedTask() {
        return this.wrapped;
    }

    @Override
    public void setParent(final ToplevelBlockTask parent) {
        super.setParent(parent);
        this.wrapped.setParent(parent);
    }

    @Override
    public int getStart() {
        return this.wrapped.getStart();
    }

    @Override
    public int getEnd() {
        return this.wrapped.getEnd();
    }

    @Override
    public void setEnd(int end) {
        super.setEnd(end);
        this.wrapped.setEnd(end);
    }

    @Override
    public void setStart(int start) {
        super.setStart(start);
        this.wrapped.setStart(start);
    }

    @Override
    public void onSuccess() {
        this.wrapped.onSuccess();
    }

    @Override
    public void onFailure(final Exception exception) {
        this.wrapped.onFailure(exception);
    }
}
