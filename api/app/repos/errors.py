class RepoError(Exception):
    pass

class NotFound(RepoError):
    pass

class Conflict(RepoError):
    pass

class Validation(RepoError):
    pass

class Transient(RepoError):
    pass
