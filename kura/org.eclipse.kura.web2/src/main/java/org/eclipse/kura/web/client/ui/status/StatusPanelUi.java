/*******************************************************************************
 * Copyright (c) 2011, 2019 Eurotech and/or its affiliates
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *     Eurotech
 *******************************************************************************/
package org.eclipse.kura.web.client.ui.status;

import java.util.Iterator;

import org.eclipse.kura.web.client.messages.Messages;
import org.eclipse.kura.web.client.messages.ValidationMessages;
import org.eclipse.kura.web.client.util.EventService;
import org.eclipse.kura.web.client.util.request.RequestQueue;
import org.eclipse.kura.web.shared.ForwardedEventTopic;
import org.eclipse.kura.web.shared.model.GwtGroupedNVPair;
import org.eclipse.kura.web.shared.model.GwtSession;
import org.eclipse.kura.web.shared.service.GwtSecurityTokenService;
import org.eclipse.kura.web.shared.service.GwtSecurityTokenServiceAsync;
import org.eclipse.kura.web.shared.service.GwtStatusService;
import org.eclipse.kura.web.shared.service.GwtStatusServiceAsync;
import org.gwtbootstrap3.client.ui.Button;
import org.gwtbootstrap3.client.ui.Well;
import org.gwtbootstrap3.client.ui.gwt.CellTable;

import com.google.gwt.cell.client.SafeHtmlCell;
import com.google.gwt.core.client.GWT;
import com.google.gwt.safehtml.shared.SafeHtml;
import com.google.gwt.safehtml.shared.SafeHtmlUtils;
import com.google.gwt.uibinder.client.UiBinder;
import com.google.gwt.uibinder.client.UiField;
import com.google.gwt.user.cellview.client.Column;
import com.google.gwt.user.cellview.client.RowStyles;
import com.google.gwt.user.cellview.client.TextColumn;
import com.google.gwt.user.client.ui.Composite;
import com.google.gwt.user.client.ui.Widget;
import com.google.gwt.view.client.ListDataProvider;

public class StatusPanelUi extends Composite {

    private static StatusPanelUiUiBinder uiBinder = GWT.create(StatusPanelUiUiBinder.class);

    interface StatusPanelUiUiBinder extends UiBinder<Widget, StatusPanelUi> {
    }

    private static final ValidationMessages msgs = GWT.create(ValidationMessages.class);
    private static final Messages MSG = GWT.create(Messages.class);

    private final GwtStatusServiceAsync gwtStatusService = GWT.create(GwtStatusService.class);
    private final GwtSecurityTokenServiceAsync gwtXSRFService = GWT.create(GwtSecurityTokenService.class);

    private GwtSession currentSession;
    private final ListDataProvider<GwtGroupedNVPair> statusGridProvider = new ListDataProvider<>();
    @UiField
    Well statusWell;
    @UiField
    Button statusRefresh;
    @UiField
    CellTable<GwtGroupedNVPair> statusGrid;

    public StatusPanelUi() {
        initWidget(uiBinder.createAndBindUi(this));
        // Set text for buttons
        this.statusRefresh.setText(MSG.refresh());

        this.statusGrid.setRowStyles(new RowStyles<GwtGroupedNVPair>() {

            @Override
            public String getStyleNames(GwtGroupedNVPair row, int rowIndex) {
                if ("cloudStatus".equals(row.getName()) || "connectionName".equals(row.getName())
                        || "networkStatusEthernet".equals(row.getName()) || "networkStatusWifi".equals(row.getName())
                        || "networkStatusModem".equals(row.getName()) || "positionStatus".equals(row.getName())) {
                    return "rowHeader";
                } else {
                    return " ";
                }
            }
        });

        loadStatusTable(this.statusGrid, this.statusGridProvider);

        this.statusRefresh.addClickHandler(e -> loadStatusData());

        EventService.Handler connectionStateChangeHandler = eventInfo -> {
            if (StatusPanelUi.this.isVisible() && StatusPanelUi.this.isAttached()) {
                loadStatusData();
            }
        };

        EventService.subscribe(ForwardedEventTopic.CLOUD_CONNECTION_STATUS_ESTABLISHED, connectionStateChangeHandler);
        EventService.subscribe(ForwardedEventTopic.CLOUD_CONNECTION_STATUS_LOST, connectionStateChangeHandler);

    }

    // get current session from UI parent
    public void setSession(GwtSession gwtBSSession) {
        this.currentSession = gwtBSSession;
    }

    // create table layout
    public void loadStatusTable(CellTable<GwtGroupedNVPair> grid, ListDataProvider<GwtGroupedNVPair> dataProvider) {
        TextColumn<GwtGroupedNVPair> col1 = new TextColumn<GwtGroupedNVPair>() {

            @Override
            public String getValue(GwtGroupedNVPair object) {
                String title = object.getName();
                if ("Connection Name".equals(title))
                    title = "connectionName";
                if ("Account".equals(title))
                    title = "account";
                try {
                    title = msgs.getString(title);
                } catch (Exception e) {
                    // northing
                }
                return String.valueOf(title);
            }
        };
        col1.setCellStyleNames("status-table-row");
        grid.addColumn(col1);

        Column<GwtGroupedNVPair, SafeHtml> col2 = new Column<GwtGroupedNVPair, SafeHtml>(new SafeHtmlCell()) {

            @Override
            public SafeHtml getValue(GwtGroupedNVPair object) {
                return SafeHtmlUtils.fromTrustedString(String.valueOf(object.getValue()));
            }
        };

        col2.setCellStyleNames("status-table-row");
        grid.addColumn(col2);
        dataProvider.addDataDisplay(grid);
    }

    // fetch table data
    public void loadStatusData() {
        this.statusGridProvider.getList().clear();
        RequestQueue.submit(c -> this.gwtXSRFService
                .generateSecurityToken(c.callback(token -> StatusPanelUi.this.gwtStatusService.getDeviceConfig(token,
                        StatusPanelUi.this.currentSession.isNetAdminAvailable(), c.callback(result -> {
                            String title = "cloudStatus";
                            StatusPanelUi.this.statusGridProvider.getList().add(new GwtGroupedNVPair(" ", title, " "));

                            Iterator<GwtGroupedNVPair> it = result.iterator();
                            while (it.hasNext()) {
                                GwtGroupedNVPair connectionName = it.next();
                                if (!title.equals(connectionName.getGroup())) {
                                    title = connectionName.getGroup();
                                    if ("Connection Name".equals(title))
                                        title = "connectionName";
                                    StatusPanelUi.this.statusGridProvider.getList()
                                            .add(new GwtGroupedNVPair(" ", title, " "));
                                }
                                StatusPanelUi.this.statusGridProvider.getList().add(connectionName);
                            }
                            int size = StatusPanelUi.this.statusGridProvider.getList().size();
                            StatusPanelUi.this.statusGrid.setVisibleRange(0, size);
                            StatusPanelUi.this.statusGridProvider.flush();
                        })))));
    }

    // public void setParent(EntryClassUi parent) {
    // }
}