"""
Test libvirt support features in qemu cmdline.
BTW it not limited to hypervisors CPU/machine features.
"""
import logging

from autotest.client.shared import error

from virttest import virsh
from virttest.libvirt_xml import vm_xml
from virttest.utils_test import libvirt

from provider import libvirt_version


def config_feature_pv_eoi(vmxml, **kwargs):
    """
    Config libvirt VM XML to enable/disable PV EOI feature.

    :param vmxml: VMXML instance
    :param kwargs: Function keywords
    :return: Corresponding feature flag in qem cmdline
    """
    # This attribute supported since 0.10.2 (QEMU only)
    if not libvirt_version.version_compare(0, 10, 2):
        raise error.TestNAError("PV eoi is not supported in current"
                                " libvirt version")
    qemu_flags = []
    eoi_enable = kwargs.get('eoi_enable', 'on')
    if eoi_enable == 'on':
        qemu_flags.append('+kvm_pv_eoi')
    elif eoi_enable == 'off':
        qemu_flags.append('-kvm_pv_eoi')
    else:
        logging.error("Invaild value %s, eoi_enable must be 'on' or 'off'",
                      eoi_enable)
    try:
        vmxml_feature = vmxml.features
        if vmxml_feature.has_feature('apic'):
            vmxml_feature.remove_feature('apic')
        vmxml_feature.add_feature('apic', 'eoi', eoi_enable)
        vmxml.features = vmxml_feature
        logging.debug("Update VM XML:\n%s", vmxml)
        vmxml.sync()
    except Exception, detail:
        logging.error("Update VM XML fail: %s", detail)
    return qemu_flags


def config_feature_memory_backing(vmxml, **kwargs):
    """
    Config libvirt VM XML to influence how virtual memory pages are backed
    by host pages.

    :param vmxml: VMXML instance
    :param kwargs: Function keywords
    :return: Corresponding feature flag in qem cmdline
    """
    # Both 'nosharepages' and 'locked' are supported since 1.0.6
    if not libvirt_version.version_compare(1, 0, 6):
        raise error.TestNAError("Element is not supported in current"
                                " libvirt version")
    qemu_flags = []
    no_sharepages = "yes" == kwargs.get("nosharepages", "no")
    locked = "yes" == kwargs.get("locked", "no")
    if no_sharepages:
        # On RHEL6, the flag is 'redhat-disable-KSM'
        # On RHEL7 & Fedora, the flag is 'mem-merge=off'
        qemu_flags.append(['mem-merge=off', 'redhat-disable-KSM'])
    if locked:
        qemu_flags.append("mlock=on")
        memtune_xml = vm_xml.VMMemTuneXML()
        memtune_xml.hard_limit = vmxml.max_mem * 4
        vmxml.memtune = memtune_xml
        vmxml.sync()
    try:
        vm_xml.VMXML.set_memoryBacking_tag(vmxml.vm_name,
                                           hpgs=False,
                                           nosp=no_sharepages,
                                           locked=locked)
        logging.debug("xml updated to %s", vmxml.xmltreefile)
    except Exception, detail:
        logging.error("Update VM XML fail: %s", detail)
    return qemu_flags


def run(test, params, env):
    """
    Test libvirt support features in qemu cmdline.

    1) Config test feature in VM XML;
    2) Try to start VM;
    3) Check corresponding feature flags in qemu cmdline;
    4) Login VM to test feature if necessary.
    """
    vm_name = params.get("main_vm", "avocado-vt-vm1")
    vm = env.get_vm(vm_name)
    expect_fail = "yes" == params.get("expect_start_vm_fail", "no")
    test_feature = params.get("test_feature")
    # All test case Function start with 'test_feature' prefix
    testcase = globals()['config_feature_%s' % test_feature]
    test_feature_attr = params.get("test_feature_attr", '').split(",")
    test_feature_valu = params.get("test_feature_valu", '').split(",")
    # Paramters for test case
    if len(test_feature_attr) != len(test_feature_valu):
        raise error.TestError("Attribute number not match with value number")
    test_dargs = dict(zip(test_feature_attr, test_feature_valu))
    if vm.is_alive():
        vm.destroy()
    vmxml = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    vmxml_backup = vmxml.copy()
    virsh_dargs = {'debug': True, 'ignore_status': False}
    try:
        # Run test case
        qemu_flags = testcase(vmxml, **test_dargs)
        result = virsh.start(vm_name, **virsh_dargs)
        libvirt.check_exit_status(result, expect_fail)

        # Check qemu flag
        vm_pid = vm.get_pid()
        cmdline_f = open("/proc/%s/cmdline" % vm_pid)
        cmdline_content = cmdline_f.read()
        cmdline_f.close()
        logging.debug("VM cmdline:\n%s",
                      cmdline_content.replace('\x00', ' '))
        msg = "Find '%s' in qemu cmdline? %s"
        found_flags = []
        index = 0
        for flag in qemu_flags:
            # Here, flag could be a list, so uniform it to list for next
            # step check. And, check can pass if any element in the list
            # exist in cmdline
            if not isinstance(flag, list):
                flag = [flag]
            found_f = []
            for f in flag:
                if f in cmdline_content:
                    found_f.append(True)
                    break
                else:
                    found_f.append(False)
            found_flags.append(any(found_f))
            logging.info(msg % (flag, found_flags[index]))
            index += 1
        if False in found_flags:
            raise error.TestFail("Not find all flags")
    finally:
        vmxml_backup.sync()
