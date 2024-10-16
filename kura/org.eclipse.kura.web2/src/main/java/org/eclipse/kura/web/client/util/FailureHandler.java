/*******************************************************************************
 * Copyright (c) 2011, 2024 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.web.client.util;

import org.eclipse.kura.web.client.messages.Messages;
import org.eclipse.kura.web.shared.GwtKuraErrorCode;
import org.eclipse.kura.web.shared.GwtKuraException;

import com.google.gwt.core.client.GWT;
import com.google.gwt.user.client.Timer;
import com.google.gwt.user.client.Window;
import com.google.gwt.user.client.rpc.StatusCodeException;

public class FailureHandler {

    private static final Messages MSGS = GWT.create(Messages.class);

    private static Backend backend = (title, message, stackTrace) -> Window.alert(title + " - " + message);

    private FailureHandler() {
    }

    public static void handle(Throwable caught, String name) {
        if (caught instanceof StatusCodeException) {
            final StatusCodeException statusCodeException = (StatusCodeException) caught;
            if (statusCodeException.getStatusCode() == 401 || statusCodeException.getStatusCode() == 403) {
                showErrorMessage(statusCodeException.getStatusCode() == 401 ? MSGS.sessionExpiredError()
                        : MSGS.unauthorizedError(), null);
                Timer timer = new Timer() {

                    @Override
                    public void run() {
                        Window.Location.reload();
                    }
                };

                timer.schedule(2000);
                return;
            }
        }
        printMessage(caught, name);
    }

    public static void handle(Throwable caught) {
        handle(caught, "");
    }

    public static void showErrorMessage(String message) {
        showErrorMessage(MSGS.warning(), message, null);
    }

    public static void showErrorMessage(final String message, final StackTraceElement[] stackTrace) {
        showErrorMessage(MSGS.warning(), message, stackTrace);
    }

    public static void showErrorMessage(final String title, final String message,
            final StackTraceElement[] stackTrace) {
        backend.showFailureMessage(title, message, stackTrace);
    }

    private static void printMessage(Throwable caught, String name) {
        StringBuilder errorMessageBuilder = new StringBuilder();
        if (name != null && !"".equals(name.trim())) {
            errorMessageBuilder.append(name);
            errorMessageBuilder.append(": ");
        }

        if (caught instanceof GwtKuraException) {

            GwtKuraException gee = (GwtKuraException) caught;
            GwtKuraErrorCode code = gee.getCode();

            switch (code) {
            case DUPLICATE_NAME:
                errorMessageBuilder.append(MSGS.duplicateNameError());
                break;
            case CONNECTION_FAILURE:
                errorMessageBuilder.append(MSGS.connectionFailure());
                break;
            case ILLEGAL_ARGUMENT:
                errorMessageBuilder.append(MSGS.illegalArgumentError());
                break;
            case ILLEGAL_NULL_ARGUMENT:
                errorMessageBuilder.append(MSGS.illegalNullArgumentError());
                break;
            case CERTIFICATE_PARSE_FAILURE:
                errorMessageBuilder.append(MSGS.certificateParseFailure());
                break;
            case PASSWORD_NEVER_SET:
                errorMessageBuilder.append(MSGS.passwordNeverSetError());
                break;
            default:
                errorMessageBuilder.append(MSGS.genericError());
            }
            if (gee.getDetailMessage() != null) {
                errorMessageBuilder.append("\n" + gee.getDetailMessage());
            }

        } else if (caught instanceof StatusCodeException && ((StatusCodeException) caught).getStatusCode() == 0) {
            // the current operation was interrupted as the user started a new one
            // or navigated away from the page.
            // we can ignore this error and do nothing.
            return;
        } else {
            String localizedMessage = caught.getLocalizedMessage();

            if (!"".equals(localizedMessage)) {
                errorMessageBuilder.append(localizedMessage);
            } else {
                errorMessageBuilder.append(MSGS.genericError());
            }
        }

        showErrorMessage(errorMessageBuilder.toString(), caught.getStackTrace());
    }

    public static void setBackend(final Backend backend) {
        FailureHandler.backend = backend;
    }

    public interface Backend {

        public void showFailureMessage(final String title, final String message, final StackTraceElement[] stackTrace);
    }
}
