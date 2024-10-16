/*******************************************************************************
 * Copyright (c) 2019, 2020 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.web2.ext;

import com.google.gwt.core.client.Callback;

public interface AuthenticationHandler {

    public String getName();

    public String getLabel();

    public WidgetFactory getLoginDialogElement();

    public void authenticate(final Callback<String, String> callback);
}
