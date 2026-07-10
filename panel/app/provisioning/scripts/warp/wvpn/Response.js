const BException=require('./bexception')
class response {
    static async _response(res, msg, success, code) {
        res.status((code ? code : 200))
        res.send({
            data: msg,
            success: success,
            code: (code ? code : 200)

        })
    }

    static async _return(msg,success,code)
    {
        throw new BException(msg,success,code)
    }
    static async _success(msg)
    {
         new BException(msg,true,200)
    }
    static async _internalError(message)
    {
        throw new BException(message ? message : "internal Error",false,500)
    }
}
module.exports=response;