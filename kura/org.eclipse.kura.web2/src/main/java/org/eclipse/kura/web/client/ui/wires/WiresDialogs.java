/*******************************************************************************
 * Copyright (c) 2017, 2018 Eurotech and/or its affiliates
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 *******************************************************************************/
package org.eclipse.kura.web.client.ui.wires;

import java.util.Map;

import org.eclipse.kura.web.client.messages.Messages;
import org.eclipse.kura.web.client.ui.KuraTextBox;
import org.eclipse.kura.web.client.util.PidTextBox;
import org.eclipse.kura.web.shared.model.GwtConfigComponent;
import org.gwtbootstrap3.client.ui.Button;
import org.gwtbootstrap3.client.ui.FormLabel;
import org.gwtbootstrap3.client.ui.ListBox;
import org.gwtbootstrap3.client.ui.Modal;
import org.gwtbootstrap3.client.ui.ModalHeader;
import org.gwtbootstrap3.client.ui.TextArea;
import org.gwtbootstrap3.client.ui.TextBox;

import com.google.gwt.core.client.GWT;
import com.google.gwt.event.dom.client.ClickEvent;
import com.google.gwt.event.dom.client.ClickHandler;
import com.google.gwt.uibinder.client.UiBinder;
import com.google.gwt.uibinder.client.UiField;
import com.google.gwt.user.client.ui.Composite;
import com.google.gwt.user.client.ui.Widget;

public class WiresDialogs extends Composite {

    interface WiresDialogsUiBinder extends UiBinder<Widget, WiresDialogs> {
    }

    private static final WiresDialogsUiBinder uiBinder = GWT.create(WiresDialogsUiBinder.class);

    private static final Messages MSGS = GWT.create(Messages.class);

    @UiField
    ListBox assetInstance;
    @UiField
    Button buttonSelectAssetCancel;
    @UiField
    Button buttonNewAsset;
    @UiField
    Button buttonSelectAssetOk;
    @UiField
    Modal selectDriverModal;
    @UiField
    ListBox driverInstance;
    @UiField
    Button buttonSelectDriverCancel;
    @UiField
    Button buttonNewDriver;
    @UiField
    Button buttonSelectDriverOk;
    @UiField
    Modal newAssetModal;
    @UiField
    PidTextBox newAssetPid;
    @UiField
    KuraTextBox newAssetDriverInstance;
    @UiField
    Button newAssetOk;
    @UiField
    Button newAssetCancel;
    @UiField
    Modal newDriverModal;
    @UiField
    PidTextBox newDriverPid;
    @UiField
    ListBox newDriverFactory;
    @UiField
    Button newDriverCancel;
    @UiField
    Button newDriverOk;
    @UiField
    Modal selectAssetModal;
    @UiField
    ModalHeader newAssetModalHeader;
    @UiField
    FormLabel componentPidLabel;
    @UiField
    Modal genericCompModal;
    @UiField
    Button btnComponentModalYes;
    @UiField
    Button btnComponentModalNo;
    @UiField
    PidTextBox componentPid;
    @UiField
    TextBox componentName;
    @UiField
    TextArea componentDesc;
    @UiField
    TextBox newDriverName;
    @UiField
    TextArea newDriverDesc;
    @UiField
    TextBox newAssetName;
    @UiField
    TextArea newAssetDesc;

    private Listener listener;
    private Callback pickCallback;

    public WiresDialogs() {
        initWidget(uiBinder.createAndBindUi(this));

        initSelectAssetModal();
        initSelectDriverModal();
        initAssetModal();
        initNewAssetModal();
        initNewDriverModal();
    }

    public void setDriverPids(Map<String, String> driverPids) {
        this.driverInstance.clear();
        driverPids.entrySet().stream().forEach(entry -> {
            this.driverInstance.addItem(entry.getValue(), entry.getKey());
        });

        driverInstance.setEnabled(!driverPids.isEmpty());
        buttonSelectDriverOk.setEnabled(!driverPids.isEmpty());
    }

    public void setDriverFactoryPids(Map<String, String> driverFactoryPidNames) {
        this.newDriverFactory.clear();
        driverFactoryPidNames.entrySet().stream().forEach(entry -> {
            this.newDriverFactory.addItem(entry.getValue(), entry.getKey());
        });

        newDriverFactory.setEnabled(!driverFactoryPidNames.isEmpty());
        newDriverOk.setEnabled(!driverFactoryPidNames.isEmpty());
    }

    public void setAssetPidNames(Map<String, String> assetPidNames) {
        this.assetInstance.clear();
        assetPidNames.entrySet().stream().forEach(entry -> {
            this.assetInstance.addItem(entry.getValue(), entry.getKey());
        });

        buttonSelectAssetOk.setEnabled(!assetPidNames.isEmpty());
    }

    private void initSelectAssetModal() {

        this.buttonNewAsset.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                WiresDialogs.this.selectDriverModal.show();
            }
        });

        this.buttonSelectAssetOk.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                if (pickCallback != null) {
                    String assetPid = WiresDialogs.this.assetInstance.getSelectedValue();
                    String name = WiresDialogs.this.assetInstance.getSelectedItemText();
                    pickCallback.onNewComponentCreated(assetPid, name, null);
                }
                selectAssetModal.hide();
            }
        });
        this.buttonSelectAssetCancel.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                if (pickCallback != null) {
                    pickCallback.onCancel();
                }
            }
        });
    }

    private void initSelectDriverModal() {
        this.buttonNewDriver.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                WiresDialogs.this.newDriverPid.setValue("");
                WiresDialogs.this.newDriverModal.show();
            }
        });

        this.buttonSelectDriverOk.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                String driverPid = WiresDialogs.this.driverInstance.getSelectedValue();
                String driverName = WiresDialogs.this.driverInstance.getSelectedItemText();
                WiresDialogs.this.newAssetDriverInstance.setText(driverName);
                WiresDialogs.this.newAssetDriverInstance.setData(driverPid);
                WiresDialogs.this.newAssetPid.setText("");
                WiresDialogs.this.newAssetModal.show();
            }
        });
        this.buttonSelectDriverCancel.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                if (pickCallback != null) {
                    pickCallback.onCancel();
                }
            }
        });
    }

    private void initNewAssetModal() {
        this.newAssetDriverInstance.setReadOnly(true);

        this.newAssetOk.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                String wireAssetPid = WiresDialogs.this.newAssetPid.getPid();
                String name = WiresDialogs.this.newAssetName.getText();
                String desc = WiresDialogs.this.newAssetDesc.getText();
                if (wireAssetPid == null || !listener.onNewPidInserted(wireAssetPid)) {
                    return;
                }
                String driverPid = WiresDialogs.this.newAssetDriverInstance.getData();
                WiresDialogs.this.newAssetModal.hide();
                if (pickCallback != null) {
                    pickCallback.onNewAssetCreated(wireAssetPid, driverPid, name, desc);
                }
            }
        });

        this.newAssetCancel.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                if (pickCallback != null) {
                    pickCallback.onCancel();
                }
            }
        });
    }

    private void initNewDriverModal() {

        this.newDriverOk.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                final String pid = WiresDialogs.this.newDriverPid.getPid();
                final String name = WiresDialogs.this.newDriverName.getText();
                final String desc = WiresDialogs.this.newDriverDesc.getText();
                if (pid == null) {
                    return;
                }
                if (listener == null || !listener.onNewPidInserted(pid)) {
                    return;
                }
                final String factoryPid = WiresDialogs.this.newDriverFactory.getSelectedValue();
                WiresRPC.createNewDriver(factoryPid, pid, name, desc, new WiresRPC.Callback<GwtConfigComponent>() {

                    @Override
                    public void onSuccess(GwtConfigComponent result) {
                        newDriverModal.hide();
                        newAssetDriverInstance.setText(name);
                        newAssetDriverInstance.setData(pid);
                        newAssetPid.setText("");
                        newAssetModal.show();
                        if (listener != null) {
                            listener.onNewDriverCreated(pid, factoryPid, name, desc, result);
                        }
                    }
                });
            }
        });

        this.newDriverCancel.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                if (pickCallback != null) {
                    pickCallback.onCancel();
                }
            }

        });
    }

    private void initAssetModal() {
        this.componentPidLabel.setText(MSGS.wiresComponentName());
        this.btnComponentModalYes.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                String value = WiresDialogs.this.componentPid.getPid();
                String name = WiresDialogs.this.componentName.getText();
                String desc = WiresDialogs.this.componentDesc.getText();
                if (value != null) {
                    if (listener == null || !listener.onNewPidInserted(value)) {
                        return;
                    }
                    if (pickCallback != null) {
                        pickCallback.onNewComponentCreated(value, name, desc);
                    }
                    genericCompModal.hide();
                    componentPid.clear();
                }
            }
        });
        this.btnComponentModalNo.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                if (pickCallback != null) {
                    pickCallback.onCancel();
                }
            }
        });
    }

    public void setListener(Listener listener) {
        this.listener = listener;
    }

    public void pickComponent(String factoryPid, Callback callback) {
        this.pickCallback = callback;
        if (factoryPid.contains(WiresPanelUi.WIRE_ASSET)) {
            if (this.assetInstance.getItemCount() > 0) {
                this.selectAssetModal.show();
            } else {
                this.selectDriverModal.show();
            }
        } else {
            this.newAssetModalHeader.setTitle(MSGS.wiresComponentNew());
            this.componentPidLabel.setText(MSGS.wiresComponentPid());
            this.componentPid.clear();
            this.newAssetPid.clear();
            this.newDriverPid.clear();
            this.genericCompModal.show();
        }
    }

    public interface Listener {

        public boolean onNewPidInserted(String pid);

        public void onNewDriverCreated(String pid, String factoryPid, String name, String desc,
                GwtConfigComponent descriptor);
    }

    public interface Callback {

        public void onNewAssetCreated(String pid, String driverPid, String name, String desc);

        public void onNewComponentCreated(String pid, String name, String desc);

        public void onCancel();
    }

}
