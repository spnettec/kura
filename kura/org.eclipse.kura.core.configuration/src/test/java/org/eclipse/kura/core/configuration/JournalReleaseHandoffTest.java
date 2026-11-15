/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;
import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.*;import java.util.*;
import org.junit.jupiter.api.Test;import org.junit.jupiter.api.io.TempDir;
class JournalReleaseHandoffTest {
 @TempDir Path root;
 @Test void committedReleaseSurvivesClosingTheCoreWithoutAnInterveningOrdinaryWrite()throws Exception {
  String previousProperty=System.getProperty(ControlledRecovery.REQUEST_PROPERTY);
  var admission=ControlledRecovery.class.getDeclaredField("admission");var completion=ControlledRecovery.class.getDeclaredField("completion");admission.setAccessible(true);completion.setAccessible(true);Object oldAdmission=admission.get(null),oldCompletion=completion.get(null);
  var core=new ConfigurationServiceImpl();
  try {
   admission.set(null,null);completion.set(null,null);System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);
   core.initializeIntentJournal(root);var field=ConfigurationServiceImpl.class.getDeclaredField("intentJournal");field.setAccessible(true);var journal=(ConfigurationIntentJournal)field.get(core);
   try(var ticket=journal.begin("plan",Set.of("owned.created","owned.deleted"))){}
   Path snapshot=root.resolve("snapshot_1.xml");Files.writeString(snapshot,"owned admitted source");String sha=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(snapshot)));
   System.setProperty(ControlledRecovery.REQUEST_PROPERTY,"owned-request");ControlledRecovery.admitNormalLoad("owned-request","owned-recovery",snapshot,sha);
   Path receipt=root.resolve("normal.properties.write-release.properties");byte[] bytes="owned explicit immutable write release\n".getBytes(java.nio.charset.StandardCharsets.UTF_8);
   ControlledRecovery.commitOrdinaryWriteRelease(ControlledRecovery.evidence().orElseThrow(),"complete-"+UUID.randomUUID(),"a".repeat(64),receipt,HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes)),()->Files.write(receipt,bytes,StandardOpenOption.CREATE_NEW));
   assertTrue(Files.exists(receipt));core.deactivate();
   // No writer ran to lazily finalize the intent. A later ordinary process has no live recovery statics.
   admission.set(null,null);completion.set(null,null);System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);
   try(var reopened=ConfigurationIntentJournal.open(root.resolve("configuration-dispatch-journal-v1"))){assertDoesNotThrow(reopened::requireStartup);assertDoesNotThrow(reopened::requireOrdinaryWrite);}
  }finally{
   core.deactivate();admission.set(null,oldAdmission);completion.set(null,oldCompletion);
   if(previousProperty==null)System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);else System.setProperty(ControlledRecovery.REQUEST_PROPERTY,previousProperty);
  }
 }
 private final class ReleaseFixture implements AutoCloseable {
  final String previousProperty=System.getProperty(ControlledRecovery.REQUEST_PROPERTY);
  final java.lang.reflect.Field admission,completion;
  final Object oldAdmission,oldCompletion;
  final ConfigurationServiceImpl core=new ConfigurationServiceImpl();
  final Path store=root.resolve("configuration-dispatch-journal-v1"),receipt=root.resolve("normal.properties.write-release.properties");
  final byte[] bytes="owned exact release publication\n".getBytes(java.nio.charset.StandardCharsets.UTF_8);
  final String receiptSha=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
  final ConfigurationIntentJournal journal;
  ReleaseFixture()throws Exception {
   admission=ControlledRecovery.class.getDeclaredField("admission");completion=ControlledRecovery.class.getDeclaredField("completion");admission.setAccessible(true);completion.setAccessible(true);oldAdmission=admission.get(null);oldCompletion=completion.get(null);
   admission.set(null,null);completion.set(null,null);System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);
   core.initializeIntentJournal(root);var field=ConfigurationServiceImpl.class.getDeclaredField("intentJournal");field.setAccessible(true);journal=(ConfigurationIntentJournal)field.get(core);
   try(var ticket=journal.begin("plan",Set.of("owned.created","owned.deleted"))){}
   Path snapshot=root.resolve("snapshot_1.xml");Files.writeString(snapshot,"owned admitted source");String sha=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(snapshot)));
   System.setProperty(ControlledRecovery.REQUEST_PROPERTY,"owned-request");ControlledRecovery.admitNormalLoad("owned-request","owned-recovery",snapshot,sha);
  }
  void release(ControlledRecovery.ReleaseCommit publish)throws Exception {
   ControlledRecovery.commitOrdinaryWriteRelease(ControlledRecovery.evidence().orElseThrow(),"complete-"+UUID.randomUUID(),"a".repeat(64),receipt,receiptSha,publish);
  }
  void clearLiveStatics()throws Exception {core.deactivate();admission.set(null,null);completion.set(null,null);System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);}
  public void close()throws Exception {core.deactivate();admission.set(null,oldAdmission);completion.set(null,oldCompletion);if(previousProperty==null)System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);else System.setProperty(ControlledRecovery.REQUEST_PROPERTY,previousProperty);}
 }
 @Test void failedPublicationDoesNotTurnItsPreparedLinkIntoARelease()throws Exception {
  try(var fixture=new ReleaseFixture()) {
   assertThrows(org.eclipse.kura.KuraException.class,()->fixture.release(()->{throw new java.io.IOException("owned before publication fault");}));
   assertThrows(org.eclipse.kura.KuraException.class,ControlledRecovery::requireOrdinaryWrite);assertFalse(Files.exists(fixture.receipt));fixture.clearLiveStatics();
   try(var reopened=ConfigurationIntentJournal.open(fixture.store)){assertThrows(org.eclipse.kura.KuraException.class,reopened::requireStartup);}
  }
 }
 @Test void exactPublishedDecisionSurvivesALostCompletionReplyWithoutReplay()throws Exception {
  try(var fixture=new ReleaseFixture()) {
   var calls=new java.util.concurrent.atomic.AtomicInteger();
   assertThrows(org.eclipse.kura.KuraException.class,()->fixture.release(()->{calls.incrementAndGet();Files.write(fixture.receipt,fixture.bytes,StandardOpenOption.CREATE_NEW);throw new java.io.IOException("owned reply lost after publish");}));
   assertEquals(1,calls.get());assertTrue(ControlledRecovery.completionEvidence().isEmpty());fixture.clearLiveStatics();
   try(var reopened=ConfigurationIntentJournal.open(fixture.store)){assertDoesNotThrow(reopened::requireStartup);assertDoesNotThrow(reopened::requireOrdinaryWrite);}
   assertEquals(1,calls.get());assertArrayEquals(fixture.bytes,Files.readAllBytes(fixture.receipt));
  }
 }
 @Test void changedPublicationNeverAuthorizesAReopenedJournal()throws Exception {
  try(var fixture=new ReleaseFixture()) {
   assertThrows(org.eclipse.kura.KuraException.class,()->fixture.release(()->Files.writeString(fixture.receipt,"wrong receipt",StandardOpenOption.CREATE_NEW)));
   fixture.clearLiveStatics();assertThrows(org.eclipse.kura.KuraException.class,()->ConfigurationIntentJournal.open(fixture.store));assertEquals("wrong receipt",Files.readString(fixture.receipt));
  }
 }
 @Test void legacyPublisherIsRejectedBeforePublishingForAnUnresolvedJournal()throws Exception {
  try(var fixture=new ReleaseFixture()) {
   var calls=new java.util.concurrent.atomic.AtomicInteger();
   assertThrows(org.eclipse.kura.KuraException.class,()->ControlledRecovery.commitOrdinaryWriteRelease(ControlledRecovery.evidence().orElseThrow(),"complete-"+UUID.randomUUID(),"a".repeat(64),calls::incrementAndGet));
   assertEquals(0,calls.get());assertThrows(org.eclipse.kura.KuraException.class,ControlledRecovery::requireOrdinaryWrite);fixture.clearLiveStatics();
   try(var reopened=ConfigurationIntentJournal.open(fixture.store)){assertThrows(org.eclipse.kura.KuraException.class,reopened::requireStartup);}
  }
 }
 @Test void incompleteRecoveryLinkKeepsGateEvenIfACompletionRecordHadReachedDisk()throws Exception {
  try(var fixture=new ReleaseFixture()) {
   Path intent;try(var files=Files.list(fixture.store)){intent=files.filter(p->p.toString().endsWith(".intent")).findFirst().orElseThrow();}
   String id=intent.getFileName().toString().substring(0,36);var bytes=new java.io.ByteArrayOutputStream();
   try(var out=new java.io.DataOutputStream(bytes)){out.writeInt(0x4b434931);out.writeUTF(id);out.writeUTF("complete");out.write(java.security.MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(intent)));}
   Files.write(fixture.store.resolve(id+".complete"),bytes.toByteArray(),StandardOpenOption.CREATE_NEW);
   assertThrows(org.eclipse.kura.KuraException.class,()->fixture.release(()->{throw new java.io.IOException("owned missing publication");}));fixture.clearLiveStatics();
   try(var reopened=ConfigurationIntentJournal.open(fixture.store)){assertThrows(org.eclipse.kura.KuraException.class,reopened::requireStartup);}
  }
 }

}
