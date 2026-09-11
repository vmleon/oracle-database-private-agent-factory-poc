# PAF kit tarball

Download the Private Agent Factory 26.7 kit from Oracle Software Delivery and
drop the tarball here. The file is ignored by git — only this README is tracked.

The computes are `VM.Standard.E5.Flex`, so the kit is the **x86_64** build. The
kit spells its architecture differently between builds, so the filename is
matched on any of `x86`, `x86_64` or `amd64` rather than one exact name.

`manage.py setup` resolves `PAF_TARBALL` to it, Terraform uploads it to Object
Storage, and the `paf` tier fetches it through a read-only pre-authenticated
request — the instance never holds OCI credentials.
