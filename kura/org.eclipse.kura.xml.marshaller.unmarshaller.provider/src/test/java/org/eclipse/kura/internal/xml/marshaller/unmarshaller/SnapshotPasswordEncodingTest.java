/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.internal.xml.marshaller.unmarshaller;

import static org.junit.jupiter.api.Assertions.*;
import java.io.*;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import javax.xml.parsers.DocumentBuilderFactory;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class SnapshotPasswordEncodingTest {
    static CryptoService crypto(AtomicInteger decrypts) {
        return (CryptoService)Proxy.newProxyInstance(CryptoService.class.getClassLoader(),new Class<?>[]{CryptoService.class},(p,m,a)->switch(m.getName()){
            case "encodeBase64" -> Base64.getEncoder().encodeToString(((String)a[0]).getBytes(StandardCharsets.UTF_8));
            case "decodeBase64" -> new String(Base64.getDecoder().decode((String)a[0]),StandardCharsets.UTF_8);
            case "decryptAes" -> {decrypts.incrementAndGet();String value=new String((char[])a[0]);if(!value.startsWith("aes:"))throw new KuraException(KuraErrorCode.DECODER_ERROR);yield value.substring(4).toCharArray();}
            default -> throw new UnsupportedOperationException(m.getName());
        });
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void streamAndDomMarkLogicalPasswordsAndDecodeExactlyOnce(boolean stream)throws Exception {
        AtomicInteger decrypts=new AtomicInteger();var mapper=new XmlJavaComponentConfigurationsMapper(crypto(decrypts));
        var config=new XmlComponentConfigurations();config.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);
        config.setConfigurations(List.of(new ComponentConfigurationImpl("owned",null,Map.of("scalar",new Password("aes:logical"),"array",new Password[]{new Password("aes:first"),new Password("")},"vector",new Vector<>(List.of(new Password("aes:vector"),new Password("")))))));
        var builder=DocumentBuilderFactory.newInstance().newDocumentBuilder();var document=builder.newDocument();
        if(stream){var out=new ByteArrayOutputStream();mapper.marshal(out,config);assertTrue(out.toString(StandardCharsets.UTF_8).contains("passwordEncoding=\"BASE64_LOGICAL_V1\""));document=builder.parse(new ByteArrayInputStream(out.toByteArray()));}
        else mapper.marshal(document,config);
        XmlComponentConfigurations decoded=mapper.unmarshal(document);assertTrue(decoded.hasLogicalPasswords());var cc=(ComponentConfigurationImpl)decoded.getConfigurations().get(0);assertTrue(cc.hasLogicalPasswords());var values=cc.getConfigurationProperties();
        assertEquals("aes:logical",values.get("scalar").toString());assertEquals("aes:first",((Password[])values.get("array"))[0].toString());assertEquals("",((Password[])values.get("array"))[1].toString());assertInstanceOf(Vector.class,values.get("vector"));assertEquals("aes:vector",((Vector<?>)values.get("vector")).get(0).toString());assertEquals(0,decrypts.get());
    }
    @Test void unmarkedLegacyPasswordRetainsItsOldAdapterPath()throws Exception {
        AtomicInteger decrypts=new AtomicInteger();var mapper=new XmlJavaComponentConfigurationsMapper(crypto(decrypts));
        var config=new XmlComponentConfigurations();config.setConfigurations(List.of(new ComponentConfigurationImpl("legacy",null,Map.of("secret",new Password("aes:legacy")))));
        var out=new ByteArrayOutputStream();mapper.marshal(out,config);assertFalse(out.toString(StandardCharsets.UTF_8).contains("passwordEncoding="));
        var doc=DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(new ByteArrayInputStream(out.toByteArray()));XmlComponentConfigurations read=mapper.unmarshal(doc);
        assertFalse(read.hasLogicalPasswords());assertFalse(((ComponentConfigurationImpl)read.getConfigurations().get(0)).hasLogicalPasswords());assertEquals("aes:legacy",read.getConfigurations().get(0).getConfigurationProperties().get("secret").toString());assertEquals(1,decrypts.get());
    }
    @Test void unknownExplicitEncodingIsRejected()throws Exception {
        var doc=DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(new ByteArrayInputStream("<esf:configurations xmlns:esf='http://eurotech.com/esf/2.0' passwordEncoding='UNKNOWN_V2'/>".getBytes(StandardCharsets.UTF_8)));
        assertThrows(IllegalArgumentException.class,()->new XmlJavaComponentConfigurationsMapper().unmarshal(doc));
    }
}
