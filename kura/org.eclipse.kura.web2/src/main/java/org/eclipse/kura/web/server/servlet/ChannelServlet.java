/*******************************************************************************
 * Copyright (c) 2018 Eurotech and/or its affiliates and others
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *  Eurotech
 *
 *******************************************************************************/
package org.eclipse.kura.web.server.servlet;

import static java.lang.String.format;
import static org.eclipse.kura.configuration.ConfigurationService.KURA_SERVICE_PID;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.io.Writer;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.http.HttpSession;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.eclipse.kura.asset.Asset;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.driver.Driver;
import org.eclipse.kura.internal.wire.asset.WireAssetChannelDescriptor;
import org.eclipse.kura.web.server.KuraRemoteServiceServlet;
import org.eclipse.kura.web.server.util.GwtServerUtil;
import org.eclipse.kura.web.server.util.ServiceLocator;
import org.eclipse.kura.web.server.util.ServiceLocator.ServiceConsumer;
import org.eclipse.kura.web.session.Attributes;
import org.eclipse.kura.web.shared.model.GwtConfigComponent;
import org.eclipse.kura.web.shared.model.GwtXSRFToken;
import org.osgi.framework.BundleContext;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ChannelServlet extends LocaleServlet {

    private static final long serialVersionUID = -1445700937173920652L;

    private static Logger logger = LoggerFactory.getLogger(ChannelServlet.class);
    private static final Logger auditLogger = LoggerFactory.getLogger("AuditLogger");

    /**
     * Instance of Base Asset Channel Descriptor
     */
    private static final GwtConfigComponent WIRE_ASSET_CHANNEL_DESCRIPTOR = GwtServerUtil
            .toGwtConfigComponent(toComponentConfiguration(WireAssetChannelDescriptor.get().getDescriptor()), null);

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        HttpSession session = req.getSession(false);
        // BEGIN XSRF - Servlet dependent code
        try {
            GwtXSRFToken token = new GwtXSRFToken(req.getParameter("xsrfToken"));
            KuraRemoteServiceServlet.checkXSRFToken(req, token);
            // END XSRF security check
            String assetPid = req.getParameter("assetPid");
            String driverPid = req.getParameter("driverPid");
            String userAgent = req.getHeader("User-Agent");
            Writer out = new StringWriter();
            CSVPrinter printer = new CSVPrinter(out, CSVFormat.RFC4180);
            String formFileName = assetPid;
            if (userAgent.contains("MSIE") || userAgent.contains("Trident")) {
                formFileName = URLEncoder.encode(formFileName, "UTF-8");
            } else {
                formFileName = new String(formFileName.getBytes("UTF-8"), "ISO-8859-1");
            }
            if (!fillCsvFields(printer, assetPid, driverPid)) {
                resp.getWriter().write("Error generating CSV output!");
            } else {
                resp.setCharacterEncoding("UTF-8");
                resp.setContentType("text/csv;charset=utf-8");
                resp.setHeader("Content-Disposition", "attachment; filename=asset_" + formFileName + ".csv");
                resp.setHeader("Cache-Control", "no-transform, max-age=0");
                try (PrintWriter writer = resp.getWriter()) {
                    writer.write(out.toString());
                }
            }

            auditLogger.info(
                    "UI Channel Servlet - Success - Successfully wrote Channel CSV description for user: {}, session: {}, asset pid: {}, driver pid: {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId(), assetPid, driverPid);
        } catch (Exception ex) {
            logger.error("Error while exporting CSV output!", ex);
            auditLogger.warn(
                    "UI Channel Servlet - Failure - Failed to write Channel CSV description for user: {}, session: {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        }
    }

    private boolean fillCsvFields(CSVPrinter printer, String assetPid, String driverPid) {
        final AtomicBoolean error = new AtomicBoolean(false);
        List<String> orderedFields = new ArrayList<>();
        try {
            WIRE_ASSET_CHANNEL_DESCRIPTOR.getParameters().forEach(i -> {
                try {
                    printer.print(i.getId().substring(1));
                } catch (IOException e) {
                    error.set(true);
                }
                orderedFields.add(new StringBuilder().append("+").append(i.getId().substring(1)).toString());
            });

            withDriver(driverPid, driver -> {
                @SuppressWarnings("unchecked")
                List<AD> descriptor = (List<AD>) driver.getChannelDescriptor().getDescriptor();

                for (AD ad : descriptor) {
                    try {
                        printer.print(ad.getId());
                    } catch (IOException e) {
                        error.set(true);
                    }
                    orderedFields.add(ad.getId());
                }
            });
            printer.println();

            withAsset(assetPid, asset -> asset.getAssetConfiguration().getAssetChannels().forEach((name, channel) -> {
                orderedFields.forEach(key -> {
                    try {
                        printer.print(channel.getConfiguration().get(key));
                    } catch (IOException e) {
                        error.set(true);
                    }
                });
                try {
                    printer.println();
                } catch (IOException e) {
                    error.set(true);
                }
            }));
        } catch (Exception ex) {
            error.set(true);
        }

        return !error.get();
    }

    private static ComponentConfiguration toComponentConfiguration(Object descriptor) {
        if (!(descriptor instanceof List<?>)) {
            return null;
        }

        final List<?> ads = (List<?>) descriptor;

        final Tocd ocd = new Tocd();
        for (final Object ad : ads) {
            if (!(ad instanceof Tad)) {
                return null;
            }
            ocd.addAD((Tad) ad);
        }
        return new ComponentConfigurationImpl("", ocd, null);
    }

    private void withAsset(final String kuraServicePid, final ServiceConsumer<Asset> consumer) throws Exception {
        final BundleContext ctx = FrameworkUtil.getBundle(ServiceLocator.class).getBundleContext();

        final String filter = format("(%s=%s)", KURA_SERVICE_PID, kuraServicePid);
        final Collection<ServiceReference<Asset>> refs = ctx.getServiceReferences(Asset.class, filter);

        if (refs == null || refs.isEmpty()) {
            return;
        }

        final ServiceReference<Asset> assetRef = refs.iterator().next();

        try {
            consumer.consume(ctx.getService(assetRef));
        } finally {
            ctx.ungetService(assetRef);
        }
    }

    private void withDriver(final String kuraServicePid, final ServiceConsumer<Driver> consumer) throws Exception {
        final BundleContext ctx = FrameworkUtil.getBundle(ServiceLocator.class).getBundleContext();

        final String filter = format("(%s=%s)", KURA_SERVICE_PID, kuraServicePid);
        final Collection<ServiceReference<Driver>> refs = ctx.getServiceReferences(Driver.class, filter);

        if (refs == null || refs.isEmpty()) {
            return;
        }

        final ServiceReference<Driver> driverRef = refs.iterator().next();

        try {
            consumer.consume(ctx.getService(driverRef));
        } finally {
            ctx.ungetService(driverRef);
        }
    }

}
