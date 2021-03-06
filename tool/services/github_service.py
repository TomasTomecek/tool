import json
import logging
import re
import time

import github
from tool.service import Service
from tool.utils import (clone_repo_and_cd_inside, fetch_all, get_commit_msgs,
                        prompt_for_pr_content, set_origin_remote,
                        set_upstream_remote)

logger = logging.getLogger(__name__)


def get_github_full_name(repo_url):
    """ convert remote url into a <namespace>/<repo> """
    s = re.sub(r"^[a-zA-Z0-9:/@]+?github.com.", "", repo_url)
    return re.sub(r"\.git$", "", s)


class GithubService(Service):
    name = "github"

    def __init__(self, token=None, full_repo_name=None):
        super().__init__(token=token)

        self.g = github.Github(login_or_token=self.token)
        self.user = self.g.get_user()
        self.repo = None
        if full_repo_name:
            self.repo = self.g.get_repo(full_repo_name)

    @classmethod
    def create_from_remote_url(cls, remote_url, **kwargs):
        """ create instance of service from provided remote_url """
        if "github.com" not in remote_url:
            return None
        full_repo_name = get_github_full_name(remote_url)
        logger.debug("github repo name: %s", full_repo_name)
        return cls(full_repo_name=full_repo_name, **kwargs)

    def _is_fork_of(self, user_repo, target_repo):
        """ is provided repo fork of gh.com/{parent_repo}/? """
        return user_repo.fork and user_repo.parent and \
               user_repo.parent.full_name == target_repo

    def fork(self, target_repo):

        target_repo_org, target_repo_name = target_repo.split("/", 1)

        target_repo_gh = self.g.get_repo(target_repo)

        try:
            # is it already forked?
            user_repo = self.user.get_repo(target_repo_name)
            if not self._is_fork_of(user_repo, target_repo):
                raise RuntimeError("repo %s is not a fork of %s" % (target_repo_gh, user_repo))
        except github.UnknownObjectException:
            # nope
            user_repo = None

        if self.user.login == target_repo_org:
            # user wants to fork its own repo; let's just set up remotes 'n stuff
            if not user_repo:
                raise RuntimeError("repo %s not found" % target_repo_name)
            clone_repo_and_cd_inside(user_repo.name, user_repo.ssh_url, target_repo_org)
        else:
            user_repo = self._fork_gracefully(target_repo_gh)

            clone_repo_and_cd_inside(user_repo.name, user_repo.ssh_url, target_repo_org)

            set_upstream_remote(clone_url=target_repo_gh.clone_url,
                                ssh_url=target_repo_gh.ssh_url,
                                pull_merge_name="pull")
        set_origin_remote(user_repo.ssh_url, pull_merge_name="pull")
        fetch_all()

    def _fork_gracefully(self, target_repo):
        """ fork if not forked, return forked repo """
        try:
            target_repo.full_name
        except github.GithubException.UnknownObjectException:
            logger.error("repository doesn't exist")
            raise RuntimeError("repo %s not found" % target_repo)
        logger.info("forking repo %s", target_repo)
        return self.user.create_fork(target_repo)

    def create_pull_request(self, target_remote, target_branch, current_branch):
        """
        TODO: push as well

        :param current_branch:
        :return:
        """
        head = "{}:{}".format(self.user.login, current_branch)
        logger.debug("PR head is: %s", head)

        base = "{}/{}".format(target_remote, target_branch)

        title, body = prompt_for_pr_content(get_commit_msgs(base))

        opts = {
            "title": title,
            "body": body,
            "base": target_branch,
            "head": head,
        }
        logger.debug("PR to be created: %s", json.dumps(opts, indent=2))
        # TODO: configurable, prompt instead maybe?
        time.sleep(4.0)
        pr = self.repo.create_pull(**opts)
        logger.info("PR link: %s", pr.html_url)
        return pr.html_url

    def list_pull_requests(self):
        return list(self.repo.get_pulls(state="open", sort="updated", direction="desc"))
